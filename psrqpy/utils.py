"""
A selection of useful functions used by the module.
"""

from __future__ import print_function, division

import warnings
import re
import datetime
import numpy as np
import requests
from bs4 import BeautifulSoup

from six import string_types
from six import BytesIO

from collections import OrderedDict

from .config import ATNF_BASE_URL, ATNF_VERSION, ADS_URL, ATNF_TARBALL, PSR_ALL, PSR_ALL_PARS, GLITCH_URL


# set formatting of warnings to not include line number and code (see
# e.g. https://pymotw.com/3/warnings/#formatting)
def warning_format(message, category, filename, lineno, file=None, line=None):
    return '{}: {}'.format(category.__name__, message)


warnings.formatwarning = warning_format


# problematic references that are hard to parse
PROB_REFS = ['bwck08', 'crf+18']


def get_catalogue(path_to_db=None):
    """
    This function will attempt to download the entire ATNF catalogue `tarball
    <http://www.atnf.csiro.au/people/pulsar/psrcat/downloads/psrcat_pkg.tar.gz>`_
    and convert it to an :class:`astropy.table.Table`. This is based on the
    method in the `ATNF.ipynb
    <https://github.com/astrophysically/ATNF-Pulsar-Cat/blob/master/ATNF.ipynb>`_
    notebook by Joshua Tan (`@astrophysically <https://github.com/astrophysically/>`_).

    Args:
        path_to_db (str): if the path to a local version of the database file
            is given then that will be read in rather than attempting to
            download the file (defaults to None).

    Returns:
        :class:`~astropy.table.Table`: a table containing the entire catalogue.

    """

    try:
        from astropy.table import Table
        from astropy.coordinates import SkyCoord
        import astropy.units as aunits
    except ImportError:
        raise ImportError('Problem importing astropy')

    if not path_to_db:
        try:
            import tarfile
        except ImportError:
            raise ImportError('Problem importing tarfile')

        # get the tarball
        try:
            pulsargzfile = requests.get(ATNF_TARBALL)
            fp = BytesIO(pulsargzfile.content)  # download and store in memory
        except IOError:
            raise IOError('Problem accessing ATNF catalogue tarball')

        try:
            # open tarball
            pulsargz = tarfile.open(fileobj=fp, mode='r:gz')

            # extract the database file
            dbfile = pulsargz.extractfile('psrcat_tar/psrcat.db')
        except IOError:
            raise IOError('Problem extracting the database file')

    else:
        try:
            dbfile = open(path_to_db)
        except IOError:
            raise IOError('Error loading given database file')

    breakstring = '@'    # break between each pulsar
    commentstring = '#'  # specifies line is a comment

    # create list of dictionaries - one for each pulsar
    psrlist = [{}]
    formats = {}  # dictionary of formats for each parameter

    # loop through lines in dbfile
    for line in dbfile.readlines():
        if isinstance(line, string_types):
            dataline = line.split()
        else:
            dataline = line.decode().split()   # Splits on whitespace

        if dataline[0][0] == commentstring:
            continue

        if dataline[0][0] == breakstring:
            # First break comes at the end of the first object and so forth
            psrlist.append({})  # New object!
            continue

        try:
            psrlist[-1][dataline[0]] = float(dataline[1])
            if dataline[0] not in formats.keys():
                formats[dataline[0]] = np.float64
        except ValueError:
            psrlist[-1][dataline[0]] = dataline[1]
            if dataline[0] not in formats.keys():
                formats[dataline[0]] = np.unicode

        if len(dataline) > 2:
            # check whether 3rd value is a float (so its an error value) or not
            try:
                float(dataline[2])
                isfloat = True
            except ValueError:
                isfloat = False

            if isfloat:
                # error values are last digit errors, so convert to actual
                # errors by finding the number of decimal places after the
                # '.' in the value string
                val = dataline[1].split(':')[-1]  # account for RA and DEC strings

                try:
                    float(val)
                except ValueError:
                    raise ValueError("Value with error is not convertable to a float")

                if dataline[2][0] == '-' or '.' in dataline[2]:
                    # negative errors or those with decimal points are absolute values
                    scalefac = 1.
                else:
                    # split on exponent
                    valsplit = re.split('e|E|d|D', val)
                    scalefac = 1.
                    if len(valsplit) == 2:
                        scalefac = 10**(-int(valsplit[1]))

                    dpidx = valsplit[0].find('.')  # find position of decimal point
                    if dpidx != -1:  # a point is found
                        scalefac *= 10**(len(valsplit[0])-dpidx-1)

                # add error column if required
                psrlist[-1][dataline[0]+'_ERR'] = float(dataline[2])/scalefac  # error entry

                if dataline[0]+'_ERR' not in formats.keys():
                    formats[dataline[0]+'_ERR'] = np.float64
            else:
                # add reference column if required
                psrlist[-1][dataline[0]+'_REF'] = dataline[2]  # reference entry

                if dataline[0]+'_REF' not in formats.keys():
                    formats[dataline[0]+'_REF'] = np.unicode

            if len(dataline) > 3:
                # last entry must(!) be a reference
                psrlist[-1][dataline[0]+'_REF'] = dataline[3]  # reference entry
                if dataline[0]+'_REF' not in formats.keys():
                    formats[dataline[0]+'_REF'] = np.unicode

    del psrlist[-1]  # Final breakstring comes at the end of the file

    # add RA and DEC in degs and JNAME/BNAME
    radec = False
    jname = False
    bname = False
    for i, psr in enumerate(list(psrlist)):
        if 'RAJ' in psr.keys() and 'DECJ' in psr.keys():
            coord = SkyCoord(psr['RAJ'], psr['DECJ'], unit=(aunits.hourangle, aunits.deg))
            psrlist[i]['RAJD'] = coord.ra.deg    # right ascension in degrees
            psrlist[i]['DECJD'] = coord.dec.deg  # declination in degrees
            radec = True

        # add 'JNAME', 'BNAME' and 'NAME'
        if 'PSRJ' in psr.keys():
            psrlist[i]['JNAME'] = psr['PSRJ']
            psrlist[i]['NAME'] = psr['PSRJ']
            jname = True

        if 'PSRB' in psr.keys():
            psrlist[i]['BNAME'] = psr['PSRB']
            bname = True

            if 'NAME' not in psrlist[i].keys():
                psrlist[i]['NAME'] = psr['PSRB']

    if radec:
        formats['RAJD'] = np.float64
        formats['DECJD'] = np.float64

    if jname:
        formats['JNAME'] = np.unicode
    if bname:
        formats['BNAME'] = np.unicode
    if jname or bname:
        formats['NAME'] = np.unicode

    # fill in all entries with all parameters
    for i, psr in enumerate(list(psrlist)):
        for key in formats.keys():
            if key not in psr.keys():
                psrlist[i][key] = None  # blank value

    dbfile.close()   # close tar file
    if not path_to_db:
        pulsargz.close()
        fp.close()   # close StringIO

    # convert into astropy table
    psrtable = Table(data=psrlist)

    # add data format
    for key in formats.keys():
        psrtable[key] = psrtable[key].astype(formats[key])

    # add units if known
    for key in PSR_ALL_PARS:
        if key in psrtable.colnames:
            if PSR_ALL[key]['units']:
                psrtable.columns[key].unit = PSR_ALL[key]['units']

                if PSR_ALL[key]['err'] and key+'_ERR' in psrtable.colnames:
                    psrtable.columns[key+'_ERR'].unit = PSR_ALL[key]['units']

    return psrtable


def get_version():
    """
    Return a string with the ATNF catalogue version number, or default to that
    defined in `ATNF_VERSION`.

    Returns:
        str: the ATNF catalogue version number.
    """

    site = requests.get(ATNF_BASE_URL)

    if site.status_code != 200:
        warnings.warn("Could not get ATNF version number, defaulting to {}".format(ATNF_VERSION), UserWarning)
        atnfversion = ATNF_VERSION
    else:
        # parse the site content with BeautifulSoup
        vsoup = BeautifulSoup(site.content, 'html.parser')

        try:
            vsoup = BeautifulSoup(site.content, 'html.parser')

            version = vsoup.find(attrs={'name': 'version'})
            atnfversion = version['value']
        except IOError:
            warnings.warn("Could not get ATNF version number, defaulting to {}".format(ATNF_VERSION), UserWarning)
            atnfversion = ATNF_VERSION

    return atnfversion


def get_glitch_catalogue(psr=None):
    """
    Return a :class:`~astropy.table.Table` containing the `Jodrell Bank pulsar
    glitch catalogue <http://www.jb.man.ac.uk/pulsar/glitches/gTable.html>`_.
    If using data from the glitch catalogue then please cite `Espinoza et al.
    (2011) <http://adsabs.harvard.edu/abs/2011MNRAS.414.1679E>`_ and the URL
    `<http://www.jb.man.ac.uk/pulsar/glitches.html>`_.

    The output table will contain the following columns:

     * `NAME`: the pulsars common name
     * `JNAME`: the pulsar name based on J2000 coordinates
     * `Glitch number`: the number of the glitch for a particular pulsar in chronological order
     * `MJD`: the time of the glitch in Modified Julian Days
     * `MJD_ERR`: the uncertainty on the glitch time in days
     * `DeltaF/F`: the fractional frequency change
     * `DeltaF/F_ERR`: the uncertainty on the fractional frequency change
     * `DeltaF1/F1`: the fractional frequency derivative change
     * `DeltaF1/F1_ERR`: the uncertainty on the fractional frequency derivative change
     * `Reference`: the glitch publication reference

    Args:
        psr (str): if a pulsar name is given then only the glitches for that
            pulsar are returned, otherwise all glitches are returned.

    Returns:
        :class:`~astropy.table.Table`: a table containing the entire glitch
            catalogue.

    Example:
        An example of using this to extract the glitches for the Crab Pulsar
        would be:

        >>> import psrqpy
        >>> gtable = psrqpy.get_glitch_catalogue(psr='J0534+2200')
        >>> print("There have been {} glitches observed from the Crab pulsar".format(len(gtable)))
        27
    """

    try:
        from astropy.table import Table
        from astropy.units import Unit
    except ImportError:
        raise ImportError('Problem importing astropy')

    # get webpage
    try:
        gt = requests.get(GLITCH_URL)
    except RuntimeError:
        warnings.warn("Count not query the glitch catalogue.", UserWarning)
        return None

    if gt.status_code != 200:
        warnings.warn("Count not query the glitch catalogue.", UserWarning)
        return None

    # parse HTML
    try:
        soup = BeautifulSoup(gt.content, 'html.parser')
    except RuntimeError:
        warnings.warn("Count not parse the glitch catalogue.", UserWarning)
        return None

    # get table rows
    rows = soup.table.find_all('tr')

    # set the table headings
    tabledict = OrderedDict()
    tabledict['NAME'] = []
    tabledict['JNAME'] = []
    tabledict['Glitch number'] = []
    tabledict['MJD'] = []
    tabledict['MJD_ERR'] = []
    tabledict['DeltaF/F'] = []
    tabledict['DeltaF/F_ERR'] = []
    tabledict['DeltaF1/F1'] = []
    tabledict['DeltaF1/F1_ERR'] = []
    tabledict['Reference'] = []

    # loop through rows: rows with glitches have their first column as an index
    for i, row in enumerate(rows):
        tds = row.find_all('td')

        if tds[0].contents[0].string is None:
            continue

        try:
            tabledict['NAME'].append(tds[1].contents[0].string)
            jname = 'J'+tds[2].contents[0].string if 'J' != tds[2].contents[0].string[0] else tds[2].contents[0].string
            tabledict['JNAME'].append(jname)
            tabledict['Glitch number'].append(int(tds[3].contents[0].string))

            for j, pname in enumerate(['MJD', 'MJD_ERR', 'DeltaF/F',
                                       'DeltaF/F_ERR', 'DeltaF1/F1',
                                       'DeltaF1/F1_ERR']):
                try:
                    val = float(tds[4+j].contents[0].string)
                except ValueError:
                    val = np.nan

                tabledict[pname].append(val)

            # get reference link if present
            try:
                ref = tds[10].contents[0].a.attrs['href']
            except AttributeError:
                ref = tds[10].contents[0].string
            tabledict['Reference'].append(ref)
        except RuntimeError:
            warnings.warn("Problem parsing glitch table", UserWarning)
            return None

    # convert to an astropy table
    table = Table(tabledict)
    table.columns['MJD'].unit = Unit('d')     # add units of days to glitch time
    table.columns['MJD_ERR'].unit = Unit('d')

    if psr is None:
        return table
    else:
        if psr not in table['NAME'] and psr not in table['JNAME']:
            warnings.warn("Pulsar '{}' not found in glitch catalogue".format(psr), UserWarning)
            return None
        else:
            if psr in table['NAME']:
                return table[table['NAME'] == psr]
            else:
                return table[table['JNAME'] == psr]


def get_references(useads=False):
    """
    Return a dictionary of paper
    `reference <http://www.atnf.csiro.au/research/pulsar/psrcat/psrcat_ref.html>`_
    in the ATNF catalogue. The keys are the ref strings given in the ATNF
    catalogue.

    Args:
        useads (bool): boolean to set whether to use the python mod:`ads`
            module to get the NASA ADS URL for the references

    Returns:
        dict: a dictionary of references.
    """

    refs = {}

    queryrefs = requests.get(ATNF_BASE_URL + 'psrcat_ref.html')

    if queryrefs.status_code != 200:
        warnings.warn("Could query the ATNF references. No references returned", UserWarning)
    else:
        try:
            refsoup = BeautifulSoup(queryrefs.content, 'html.parser')

            # get table containing the references
            pattern = re.compile('References')  # References are in a h2 tag containing 'References'
            # get the table in the same parent element as the 'References' header
            table = refsoup.find('h2', text=pattern).parent.find('table')

            trows = table.find_all('tr')
        except IOError:
            warnings.warn("Could not get ATNF reference list", UserWarning)
            return refs

        # loop over rows
        j = 0
        for tr in trows:
            j = j + 1
            reftag = tr.b.text  # the reference string is contained in a <b> tag

            if reftag in PROB_REFS:
                continue

            refs[reftag] = {}
            tds = tr.find_all('td')  # get the two <td> tags - reference info is in the second

            # check if publication is 'awkward', i.e. if has a year surrounded by '.'s, e.g, '.1969.' or '.1969a.'
            utext = re.sub(r'\s+', ' ', tds[1].text)
            dotyeardot = re.compile(r'\.(\d+\D?)\.')
            dotyeardotlist = dotyeardot.split(utext)
            if len(dotyeardotlist) != 3:
                utext = None

            refdata = list(tds[1].contents)  # copy list so contents of table aren't changed in the journal name substitution step below

            # check that the tag contains a string (the paper/book title) within <i> (paper) or <b> (book) - there are a few exceptions to this rule
            titlestr = None
            booktitlestr = None
            if tds[1].find('i') is not None:
                titlestr = tds[1].i.text
            if tds[1].find('b') is not None:
                booktitlestr = tds[1].b.text

            # change some journal refs that contain '.' (this causes issues when splitting authors based on '.,')
            for ridx, rdf in enumerate(list(refdata)):
                # subtitute some journal names to abbreviated versions
                journalsubs = {'Chin. J. Astron. Astrophys.': 'ChJAA',
                               'Astrophys. Lett.': 'ApJL',
                               'Res. Astron. Astrophys.': 'RAA',
                               'J. Astrophys. Astr.': 'JApA',
                               'Curr. Sci.': 'Current Science',
                               'Astrophys. Space Sci.': 'Ap&SS',
                               'Nature Phys. Sci.': 'NPhS',
                               'Sov. Astron. Lett.': 'SvAL',
                               'ATel.': 'ATel'}

                if isinstance(rdf, string_types):  # only run on string values
                    rdfs = re.sub(r'\s+', ' ', rdf)  # make sure only single spaces are present
                    for js in journalsubs:
                        if js in rdfs:
                            refdata[ridx] = re.sub(js, journalsubs[js], rdfs)

            if (titlestr is not None or booktitlestr is not None) and utext is None:
                authors = re.sub(r'\s+', ' ', refdata[0]).strip().strip('.')  # remove line breaks and extra spaces (and final full-stop)
                sepauthors = authors.split('.,')
            elif utext is not None:
                year = int(re.sub(r'\D', '', dotyeardotlist[1]))  # remove any non-number values
                authors = dotyeardotlist[0]
                sepauthors = authors.split('.,')
            else:
                sepauthors = re.sub(r'\s+', ' ', refdata[0]).split('.,')[:-1]

            if (titlestr is not None or booktitlestr is not None) and utext is None:
                try:
                    year = int(''.join(filter(lambda x: x.isdigit(), sepauthors.pop(-1).strip('.'))))  # strip any non-digit characters (e.g. from '1976a')
                except ValueError:
                    # get year from reftag
                    year = int(''.join(filter(lambda x: x.isdigit(), reftag)))
                    thisyear = int(str(datetime.datetime.now().year)[-2:])
                    if year > thisyear:
                        year += 1900
                    else:
                        year += 2000
            elif utext is None:
                rd = re.sub(r'\s+', ' ', refdata[0]).split('.,')[-1].split()
                try:
                    year = int(''.join(filter(lambda x: x.isdigit(), rd[0].strip('.'))))
                except ValueError:
                    # get year from reftag
                    year = int(''.join(filter(lambda x: x.isdigit(), reftag)))
                    thisyear = int(str(datetime.datetime.now().year)[-2:])
                    if year > thisyear:
                        year += 1900
                    else:
                        year += 2000

            if '&' in sepauthors[-1] or 'and' in sepauthors[-1]:  # split any authors that are seperated by an ampersand
                lastauthors = [a.strip() for a in re.split(r'& | and ', sepauthors.pop(-1))]
                sepauthors = sepauthors + lastauthors
                for i in range(len(sepauthors)-2):
                    sepauthors[i] += '.'  # re-add final full stops where needed
                sepauthors[-1] += '.'
            else:
                sepauthors = [a+'.' for a in sepauthors]  # re-add final full stops

            refs[reftag]['authorlist'] = ', '.join(sepauthors)
            refs[reftag]['authors'] = sepauthors
            refs[reftag]['year'] = year
            refs[reftag]['journal'] = ''
            refs[reftag]['volume'] = ''
            refs[reftag]['pages'] = ''

            if titlestr is not None:
                title = (re.sub(r'\s+', ' ', titlestr)).lstrip()  # remove any leading spaces
            else:
                title = ''
            refs[reftag]['title'] = title

            if booktitlestr is not None:
                booktitle = (re.sub(r'\s+', ' ', booktitlestr)).lstrip()
                refs[reftag]['booktitle'] = booktitle

            if titlestr is not None:
                # separate journal name, volume and pages
                journalref = [a.strip() for a in refdata[-1].strip('.').split(',')]
                if len(journalref) == 3:
                    refs[reftag]['journal'] = journalref[0]
                    refs[reftag]['volume'] = journalref[1]
                    refs[reftag]['pages'] = journalref[2]
                else:
                    if 'arxiv' in refdata[-1].strip('.').lower():
                        axvparts = refdata[-1].strip('.').split(':')
                        if len(axvparts) == 2:  # if an arXiv number of found
                            axv = 'arXiv:{}'.format(re.split(', |. ', axvparts[1])[0])
                        else:
                            axv = 'arXiv'  # no arXiv number can be set
                        refs[reftag]['journal'] = axv
            elif booktitlestr is not None:
                # separate book volume and other editorial/publisher info
                bookref = [a.strip() for a in refdata[-1].strip('.').split('eds')]
                refs[reftag]['volume'] = re.sub(r', |. |\s+', '', bookref[0])
                refs[reftag]['eds'] = bookref[1]
            else:
                refs[reftag]['year'] = year

                # split on year
                if utext is None:
                    rd = re.sub(r'\s+', ' ', refdata[0]).split('{}'.format(year))[1].split(',')
                else:
                    rd = re.sub(r'\s+', ' ', dotyeardotlist[-1]).split(',')

                if 'PhD thesis' in rd[0]:
                    refs[reftag]['journal'] = 'PhD thesis'
                    refs[reftag]['thesis pub. info.'] = ' '.join(rd[1:]).lstrip()
                else:
                    if len(rd) >= 1:
                        refs[reftag]['journal'] = rd[0].strip()
                    if len(rd) >= 2:
                        refs[reftag]['volume'] = rd[1].strip()
                    if len(rd) >= 3:
                        refs[reftag]['pages'] = rd[2].strip().strip('.')

            # get ADS entry
            if useads:
                try:
                    import ads
                except ImportError:
                    warnings.warn('Could not import ADS module, so no ADS information will be included', UserWarning)
                    continue

                refs[reftag]['ADS'] = None
                refs[reftag]['ADS URL'] = ''

                try:
                    article = ads.SearchQuery(year=refs[reftag]['year'], first_author=refs[reftag]['authors'][0], title=refs[reftag]['title'])
                except IOError:
                    warnings.warn('Could not get reference information, so no ADS information will be included', UserWarning)
                    continue

                article = list(article)

                if len(article) > 0:
                    refs[reftag]['ADS'] = list(article)[0]
                    refs[reftag]['ADS URL'] = ADS_URL.format(list(article)[0].bibcode)

    return refs


# string of logical expressions for use in regex parser
LOGEXPRS = (r'(\bAND\b'        # logical AND
            r'|\band\b'        # logical AND
            r'|\&\&'           # logical AND
            r'|\bOR\b'         # logical OR
            r'|\bor\b'         # logical OR
            r'|\|\|'           # logical OR
            r'|!='             # not equal to
            r'|=='             # equal to
            r'|<='             # less than or equal to
            r'|>='             # greater than or equal to
            r'|<'              # less than
            r'|>'              # greater than
            r'|\('             # left opening bracket
            r'|\)'             # right closing bracket
            r'|\bNOT\b'        # logical NOT
            r'|\bnot\b'        # logical NOT
            r'|!'              # logical NOT
            r'|~'              # logical NOT
            r'|\bASSOC\b'      # pulsar association
            r'|\bassoc\b'      # pulsar association
            r'|\bTYPE\b'       # pulsar type
            r'|\btype\b'       # pulsar type
            r'|\bBINCOMP\b'    # pulsar binary companion type
            r'|\bbincomp\b'    # pulsar binary companion type
            r'|\bEXIST\b'      # pulsar parameter exists in the catalogue
            r'|\bexist\b'      # pulsar parameter exists in the catalogue
            r'|\bERROR\b'      # condition on parameter error
            r'|\berror\b)')    # condition on parameter error


def condition(table, expression, exactMatch=False):
    """
    Apply a logical expression to a table of values.

    Args:
        table (:class:`astropy.table.Table`, :class:`pandas.DataFrame`): a
            table of pulsar data
        expression (str, :class:`~numpy.ndarray): a string containing a set of
            logical conditions with respect to pulsar parameter names (also
            containing `conditions
            <http://www.atnf.csiro.au/research/pulsar/psrcat/psrcat_help.html?type=normal#condition>`_
            allowed when accessing the ATNF Pulsar Catalogue), or a boolean
            array of the same length as the table.
        exactMatch

    Returns:
        table: the table of values conforming to the input condition.
            Depending on the type of input table the returned table will either
            be a :class:`astropy.table.Table` or :class:`pandas.DataFrame`.

    Example:
        Some examples this might be:

        1. finding all pulsars with frequencies greater than 100 Hz

        >>> newtable = condition(psrtable, 'F0 > 100')

        2. finding all pulsars with frequencies greater than 50 Hz and
        period derivatives less than 1e-15 s/s.

        >>> newtable = condition(psrtable, '(F0 > 50) & (P1 < 1e-15)')

        3. finding all pulsars in binary systems

        >>> newtable = condition(psrtable, 'TYPE(BINARY)')

        4. parsing a boolean array equivalent to the first example

        >>> newtable = condition(psrtable, psrtable['F0'] > 100)

    """

    from astropy.table import Table
    from pandas import DataFrame

    # check if expression is just a boolean array
    if isinstance(expression, np.ndarray):
        if expression.dtype != np.bool:
            raise TypeError("Numpy array must be a boolean array")
        elif len(expression) != len(table):
            raise Exception("Boolean array and table must be the same length")
        else:
            return table[expression]
    else:
        if not isinstance(expression, string_types):
            raise TypeError("Expression must be a boolean array or a string")

    # parse the expression string and split into tokens
    reg = re.compile(LOGEXPRS)
    tokens = reg.split(expression)
    tokens = [t.strip() for t in tokens if t.strip() != '']

    if isinstance(table, Table):
        # convert astropy table to pandas DataFrame
        tab = table.to_pandas()
    elif not isinstance(table, DataFrame):
        raise TypeError("Table must be a pandas DataFrame or astropy Table")
    else:
        tab = table

    matchTypes = ['ASSOC', 'TYPE', 'BINCOMP', 'EXIST', 'ERROR']

    # parse through tokens and replace as required
    ntokens = len(tokens)
    newtokens = []
    i = 0
    while i < ntokens:
        if tokens[i] in [r'&&', r'AND']:
            # replace synonyms for '&' or 'and'
            newtokens.append(r'&')
        elif tokens[i] in [r'||', r'OR']:
            # replace synonyms for '|' or 'or'
            newtokens.append(r'|')
        elif tokens[i] in [r'!', r'NOT', r'not']:
            # replace synonyms for '~'
            newtokens.append(r'~')
        elif tokens[i].upper() in matchTypes:
            if ntokens < i+3:
                warnings.warn("A '{}' must be followed by a '(NAME)': ignoring in query".format(tokens[i].upper()), UserWarning)
            elif tokens[i+1] != '(' or tokens[i+3] != ')':
                warnings.warn("A '{}' must be followed by a '(NAME)': ignoring in query".format(tokens[i].upper()), UserWarning)
            else:
                if tokens[i].upper() == 'ASSOC':
                    if 'ASSOC' not in tab.keys():
                        warnings.warn("'ASSOC' parameter not in table: ignoring in query", UserWarning)
                    elif exactMatch:
                        newtokens.append(r'(ASSOC == "{}")'.format(tokens[i+2]))
                    else:
                        assoc = np.array([tokens[i+2] in a for a in table['ASSOC']])
                        newtokens.append(r'(@assoc)')
                elif tokens[i].upper() == 'TYPE':
                    if tokens[i+2].upper() == 'BINARY':
                        if 'BINARY' not in tab.keys():
                            warnings.warn("'BINARY' parameter not in table: ignoring in query", UserWarning)
                        else:
                            newtokens.append(r'(BINARY != "None")')
                    else:
                        if 'TYPE' not in tab.keys():
                            warnings.warn("'TYPE' parameter not in table: ignoring in query", UserWarning)
                        elif exactMatch:
                            newtokens.append(r'(TYPE == "{}")'.format(tokens[i+2]))
                        else:
                            ttype = np.array([tokens[i+2] in a for a in table['TYPE']])
                            newtokens.append(r'(@ttype)')
                elif tokens[i].upper() == 'BINCOMP':
                    if 'BINCOMP' not in tab.keys():
                        warnings.warn("'BINCOMP' parameter not in table: ignoring in query", UserWarning)
                    elif exactMatch:
                        newtokens.append(r'(BINCOMP == "{}")'.format(tokens[i+2]))
                    else:
                        bincomp = np.array([tokens[i+2] in a for a in table['BINCOMP']])
                        newtokens.append(r'(@bincomp)')
                elif tokens[i].upper() == 'EXIST':
                    if tokens[i+2] not in tab.keys():
                        warnings.warn("'{}' does not exist for any pulsar".format(tokens[i+2]), UserWarning)
                        # create an empty DataFrame
                        tab = DataFrame(columns=table.keys())
                        break
                    else:
                        newtokens.append('({} != None)'.format(tokens[i+2]))
                elif tokens[i].upper() == 'ERROR':
                    if tokens[i+2]+'_ERR' not in tab.keys():
                        warnings.warn("Error value for '{}' not present: ignoring in query".format(tokens[i+2]), UserWarning)
                    else:
                        newtokens.append(r'{}_ERR'.format(tokens[i+2]))
            i += 2
        else:
            newtokens.append(tokens[i])

        i += 1

    # evaluate the expression
    try:
        newtab = tab.query(''.join(newtokens))
    except RuntimeError:
        raise RuntimeError("Could not parse the query")

    if isinstance(table, Table):
        # convert back to an astropy table
        newtab = Table.from_pandas(newtab)

        # re-add any units/types
        for key in table.colnames:
            newtab.columns[key].unit = table.columns[key].unit
            newtab[key] = newtab[key].astype(table[key].dtype)

    return newtab


def characteristic_age(period, pdot, braking_idx=3.):
    """
    Function defining the characteristic age of a pulsar. Returns the
    characteristic age in using

    .. math::

       \\tau = \\frac{P}{\dot{P}(n-1)}

    Args:
        period (float): the pulsar period in seconds
        pdot (float): the pulsar period derivative
        braking_idx (float): the pulsar braking index (defaults to :math:`n=3`)

    Returns:
        float: the characteristic age in years
    """

    # check everything is positive, otherwise return NaN
    if period < 0.:
        warnings.warn("The period must be positive to define a characteristic age", UserWarning)
        return np.nan

    if pdot < 0.:
        warnings.warn("The period derivative must be positive to define a characteristic age", UserWarning)
        return np.nan

    if braking_idx < 0.:
        warnings.warn("The braking index must be positive to define a characteristic age", UserWarning)
        return np.nan

    return (period/(pdot * (braking_idx - 1.)))/(365.25*86400.)


def age_pdot(period, tau=1e6, braking_idx=3.):
    """
    Function returning the period derivative for a pulsar with a given period
    and characteristic age, using

    .. math::

       \dot{P} = \\frac{P}{\\tau(n - 1)}

    Args:
        period (list, :class:`numpy.ndarray`): the pulsar period in seconds
        tau (float): the characteristic age in years
        braking_idx (float): the pulsar braking index (defaults to :math:`n=3`)

    Returns:
        :class:`numpy.ndarray`: an array of period derivatives.
    """

    periods = period
    if not isinstance(periods, np.ndarray):
        periods = np.array(periods)

    taus = tau*365.25*86400.  # tau in seconds

    pdots = (periods/(taus * (braking_idx - 1.)))
    pdots[pdots < 0] = np.nan  # set any non zero values to NaN

    return pdots


def B_field(period, pdot):
    """
    Function defining the polar magnetic field strength at the surface of the
    pulsar in gauss (Equation 5.12 of Lyne & Graham-Smith, Pulsar Astronmy, 2nd
    edition) with

    .. math::

       B = 3.2\!\\times\!10^{19} \\sqrt{P\dot{P}}

    Args:
        period (float): a pulsar period (s)
        pdot (float): a period derivative

    Returns:
        float: the magnetic field strength in gauss.
    """

    assert isinstance(period, float) or isinstance(period, int), "Period '{}' must be a number".format(period)
    assert isinstance(pdot, float) or isinstance(pdot, int), "Period derivtaive '{}' must be a number".format(pdot)

    # check everything is positive, otherwise return 0
    if period < 0.:
        warnings.warn("The period must be positive to define a magnetic field strength", UserWarning)
        return 0.

    if pdot < 0.:
        warnings.warn("The period derivative must be positive to define a magnetic field streng", UserWarning)
        return 0.

    return 3.2e19 * np.sqrt(period * pdot)


def B_field_pdot(period, Bfield=1e10):
    """
    Function to get the period derivative from a given pulsar period and
    magnetic field strength using

    .. math::

       \dot{P} = \\frac{1}{P}\left( \\frac{B}{3.2\!\\times\!10^{19}} \\right)^2

    Args:
        period (list, :class:`~numpy.ndarray`): a list of period values
        Bfield (float): the polar magnetic field strength (Defaults to
            :math:`10^{10}` G)

    Returns:
        :class:`numpy.ndarray`: an array of period derivatives
    """

    periods = period
    if not isinstance(periods, np.ndarray):
        periods = np.array(periods)

    pdots = (Bfield/3.2e19)**2/periods
    pdots[pdots < 0] = np.nan  # set any non zero values to NaN

    return pdots


def death_line(logP, linemodel='Ip', rho6=1.):
    """
    The pulsar death line. Returns the base-10 logarithm of the period
    derivative for the given values of the period.

    Args:
        logP (list, :class:`~numpy.ndarray`): the base-10 log values of period.
        linemodel (str): a string with one of the above model names. Defaults
            to ``'Ip'``.
        rho6 (float): the value of the :math:`\\rho_6` parameter from [ZHM]_ .
            Defaults to 1 is, which is equivalent to :math:`10^6` cm.

    Returns:
        :class:`numpy.ndarray`: a vector of period derivative values

    .. note::

        The death line models can be:

        * 'I' - Equation 3 of [ZHM]
        * 'Ip' - Equation 4 of [ZHM]
        * 'II' - Equation 5 of [ZHM]
        * 'IIp' - Equation 6 of [ZHM]
        * 'III' - Equation 8 of [ZHM]
        * 'IIIp' - Equation 9 of [ZHM]
        * 'IV' - Equation 10 of [ZHM]
        * 'IVp' - Equation 11 of [ZHM]

    .. [ZHM] Zhang, Harding & Muslimov, *ApJ*, **531**, L135-L138 (2000),
        `arXiv:astro-ph/0001341 <https://arxiv.org/abs/astro-ph/0001341>`_

    """

    gradvals = {'I': (11./4), 'Ip': (9./4.), 'II': (2./11.), 'IIp': -(2./11.), 'III': (5./2.), 'IIIp': 2., 'IV': -(3./11.), 'IVp': -(7./11.)}
    intercept = {'I': 14.62, 'Ip': 16.58, 'II': 13.07, 'IIp': 14.50, 'III': 14.56, 'IIIp': 16.52, 'IV': 15.36, 'IVp': 16.79}
    rho = {'I': 0., 'Ip': 1., 'II': 0., 'IIp': (8./11.), 'III': 0., 'IIIp': 1., 'IV': 0., 'IVp': (8./11.)}

    lp = logP
    if not isinstance(lp, np.ndarray):
        lp = np.array(lp)

    return lp*gradvals[linemodel] - intercept[linemodel] + rho[linemodel]*np.log10(rho6)


def label_line(ax, line, label, color='k', fs=14, frachoffset=0.1):
    """
    Add an annotation to the given line with appropriate placement and
    rotation.

    Based on code from `"How to rotate matplotlib annotation to match a line?"
    <http://stackoverflow.com/a/18800233/230468>`_ and `this
    <https://stackoverflow.com/a/38414616/1862861>`_ answer.

    Args:
        ax (:class:`matplotlib.axes.Axes`): Axes on which the label should be
            added.
        line (:class:`matplotlib.lines.Line2D`): Line which is being labeled.
        label (str): Text which should be drawn as the label.
        color (str): a color string for the label text. Defaults to ``'k'``
        fs (int): the font size for the label text. Defaults to 14.
        frachoffset (float): a number between 0 and 1 giving the fractional
            offset of the label text along the x-axis. Defaults to 0.1, i.e.,
            10%.

    Returns:
        :class:`matplotlib.text.Text`: an object containing the label
            information

    """
    xdata, ydata = line.get_data()
    x1 = xdata[0]
    x2 = xdata[-1]
    y1 = ydata[0]
    y2 = ydata[-1]

    # use fractional horizontal offset frachoffset to set the x position of the label by default
    # other wise use the halign value
    if frachoffset >= 0 and frachoffset <= 1:
        if ax.get_xscale() == 'log':
            xx = np.log10(x1) + frachoffset*(np.log10(x2) - np.log10(x1))
        else:
            xx = x1 + frachoffset*(x2 - x1)
    else:
        raise ValueError("frachoffset must be between 0 and 1".format(halign))

    if ax.get_xscale() == 'log' and ax.get_yscale() == 'log':
        yy = np.interp(xx, np.log10(xdata), np.log10(ydata))
        xx = 10**xx
        yy = 10**yy
    elif ax.get_xscale() == 'log' and ax.get_yscale() != 'log':
        yy = np.interp(xx, np.log10(xdata), ydata)
        xx = 10**xx
    else:
        yy = np.interp(xx, xdata, ydata)

    ylim = ax.get_ylim()
    xytext = (0, 5)
    text = ax.annotate(label, xy=(xx, yy), xytext=xytext, textcoords='offset points',
                       size=fs, color=color, zorder=1,
                       horizontalalignment='left', verticalalignment='center_baseline')

    sp1 = ax.transData.transform_point((x1, y1))
    sp2 = ax.transData.transform_point((x2, y2))

    rise = (sp2[1] - sp1[1])
    run = (sp2[0] - sp1[0])

    slope_degrees = np.degrees(np.arctan2(rise, run))
    text.set_rotation_mode('anchor')
    text.set_rotation(slope_degrees)
    ax.set_ylim(ylim)
    return text
