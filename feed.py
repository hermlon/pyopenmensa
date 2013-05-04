# -*- coding: UTF-8 -*-
import re
from xml.dom.minidom import Document
import datetime
try:
    from collections import OrderedDict
except ImportError:  # support python 2.6
    OrderedDict = dict


# Helpers to extract dates from strings
# -------------------------------------

date_format = re.compile(".*?(?P<datestr>(" +
                         "\d{2}(\d{2})?-[01]?\d-[0-3]?\d|" +
                         "[0-3]?\d\.[01]?\d\.\d{2}(\d{2})?|" +
                         "(?P<day>[0-3]?\d)\.? ?(?P<month>\S+) ?" +
                         "(?P<year>\d{2}(\d{2})?))).*",
                         re.UNICODE)
month_names = {
    'januar': '01',
    'january': '01',
    'februar': '02',
    'february': '02',
    'märz': '03',
    'maerz': '03',
    'march': '03',
    'april': '04',
    'mai': '05',
    'may': '05',
    'juni': '06',
    'june': '06',
    'juli': '07',
    'july': '07',
    'august': '08',
    'september': '09',
    'oktober': '10',
    'october': '10',
    'november': '11',
    'dezember': '12',
    'december': '12',
}


def extractDate(text):
    """ extract date"""
    if type(text) is datetime.date:
        return text
    match = date_format.search(text.lower())
    if not match:
        raise ValueError('unsupported date format: {0}'.format(text.lower()))
    # convert DD.MM.YYYY into YYYY-MM-DD
    if match.group('month'):
        if not match.group('month') in month_names:
            raise ValueError('unknown month names: "{0}"'
                             .format(match.group('month')))
        year = int(match.group('year'))
        return datetime.date(
            year if year > 2000 else 2000 + year,
            int(month_names[match.group('month')]),
            int(match.group('day')))
    else:
        parts = list(map(lambda v: int(v), '-'.join(reversed(
            match.group('datestr').split('.'))).split('-')))
        if parts[0] < 2000:
            parts[0] += 2000
        return datetime.date(*parts)


class extractWeekDates():
    weekdays = {
        0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6,
        'Mon': 0,
        'Montag': 0,
        'Dienstag': 1,
        'Mittwoch': 2,
        'Donnerstag': 3,
        'Freitag': 4,
        'Samstag': 5,
        'Sonntag': 6
    }

    def __init__(self, start, end=None):
        self.monday = extractDate(start)

    def __getitem__(self, value):
        if type(value) not in [int, str]:
            raise TypeError
        if value not in self.weekdays:
            raise ValueError
        return self.monday + datetime.date.resolution * self.weekdays[value]

    def __iter__(self):
        for i in range(7):
            yield self.monday + datetime.date.resolution * i


# Helpers for price handling
# -------------------------------------
default_price_regex = re.compile('(?P<price>\d+[,.]\d{2}) ?(€)?', re.UNICODE)


def convertPrice(variant, regex=default_price_regex):
    if type(variant) is int:
        return variant
    elif type(variant) is float:
        return round(variant * 100)
    elif type(variant) is str:
        match = regex.search(variant)
        if not match:
            raise ValueError('Could not extract price: {0}'.format(variant))
        return int(match.group('price').replace(',', '').replace('.', ''))
    else:
        raise TypeError('Unknown price type: {0!r}'.format(variant))


def buildPrices(data, roles=None, regex=default_price_regex,
                default=None, additional={}):
    if type(data) is dict:
        return dict(map(lambda item: (item[0], convertPrice(item[1])),
                        data.items()))
    elif type(data) in [str, float, int]:
        if default is None:
            raise ValueError('You have to call setAdditionalCharges '
                             'before it is possible to pass a string as price')
        price = convertPrice(data)
        prices = {default: price}
        for role in additional:
            prices[role] = price + convertPrice(additional[role])
        return prices
    elif roles:
        prices = {}
        priceRoles = iter(roles)
        for price in data:
            prices[next(priceRoles)] = convertPrice(price)
        return prices
    else:
        raise TypeError('This type is for prices not supported!')


# Helpers for notes and legend handling
# -------------------------------------
default_legend_regex = '(?P<name>(\d|[a-z])+)\)\s*' + \
                       '(?P<value>\w+((\s+\w+)*[^0-9)]))'
default_extra_regex = re.compile('\((?P<extra>[0-9a-zA-Z]{1,2}'
                                 '(?:,[0-9a-zA-Z]{1,2})*)\)', re.UNICODE)


def buildLegend(legend={}, text=None, regex=default_legend_regex):
    if text is not None:
        for match in re.finditer(regex, text, re.UNICODE):
            legend[match.group('name')] = match.group('value').strip()
    return legend


def extractNotes(name, notes, legend=None, regex=default_extra_regex):
    if legend is None:
        return name, notes
    # extract note
    for note in list(','.join(regex.findall(name)).split(',')):
        if note and note in legend:
            if legend[note] not in notes:
                notes.append(legend[note])
        elif note:  # skip empty notes
            print('could not find extra note "{0}"'.format(note))
    # from notes from name
    name = regex.sub('', name).replace('\xa0', ' ').replace('  ', ' ').strip()
    return name, notes


# Basic canteen with meal data
# ----------------------------


class BasicCanteen():
    """ This class represents and stores all informations
        about OpenMensa canteens. It helps writing new
        python parsers with helper and shortcuts methods.
        So the complete object can be converted to a valid
        OpenMensa v2 xml feed string. """

    def __init__(self):
        self._days = {}

    def addMeal(self, date, category, name, notes=[], prices={}):
        """ This is the main helper, it adds a meal to the
            canteen. The following data are needed:
            * date date: Date for the meal
            * categor str: Name of the meal category
            * name str: Meal name
            Additional the following data are also supported:
            * notes list[]: List of notes (as List of strings)
            * prices {str: int}: Price of the meal; Every
            key must be a string for the role of the persons
            who can use this tariff; The value is the price in Euro Cents,
            The site of the OpenMensa project offers more detailed
            information."""
        # ensure we have an entry for this date
        date = self._handleDate(date)
        if date not in self._days:
            self._days[date] = OrderedDict()
        # ensure we have a category element for this category
        if category not in self._days[date]:
            self._days[date][category] = []
        # add meal into category:
        self._days[date][category].append((name, notes, prices))

    def setDayClosed(self, date):
        self._days[self._handleDate(date)] = False

    def clearDay(self, date):
        date = self._handleDate(date)
        if date in self._days:
            del self._days[date]

    def dayCount(self):
        return len(self._days)

    def hasMealsFor(self, date):
        date = self._handleDate(date)
        if date not in self._days or self._days[date] is False:
            return False
        return len(self._days[date]) > 0

    @staticmethod
    def _handleDate(date):
        if type(date) is not datetime.date:
            raise TypeError('Dates needs to be specified by datetime.date')
        return date

    # methods to create feed
    # ----------------------
    def toXMLFeed(self):
        """ Convert this cateen information into string
            which is a valid OpenMensa v2 xml feed"""
        feed, document = self._createDocument()
        feed.appendChild(self.toTag(document))
        xml_header = '<?xml version="1.0" encoding="UTF-8"?>\n'
        return xml_header + feed.toprettyxml(indent='  ')

    @staticmethod
    def _createDocument():
        # create xml document
        output = Document()
        # build main openmensa element with correct xml namespaces
        openmensa = output.createElement('openmensa')
        openmensa.setAttribute('version', '2.0')
        openmensa.setAttribute('xmlns', 'http://openmensa.org/open-mensa-v2')
        openmensa.setAttribute('xmlns:xsi',
                               'http://www.w3.org/2001/XMLSchema-instance')
        openmensa.setAttribute('xsi:schemaLocation',
                               'http://openmensa.org/open-mensa-v2 ' +
                               'http://openmensa.org/open-mensa-v2.xsd')
        return openmensa, output

    def toTag(self, output):
        # create canteen tag, which represents our data
        canteen = output.createElement('canteen')
        # iterate above all days (sorted):
        for date in sorted(self._days.keys()):
            day = output.createElement('day')
            day.setAttribute('date', str(date))
            if self._days[date] is False:  # canteen closed
                closed = output.createElement('closed')
                day.appendChild(closed)
                canteen.appendChild(day)
                continue
            # canteen is open
            for categoryname in self._days[date]:
                day.appendChild(self._buildCategoryTag(
                    categoryname, self._days[date][categoryname], output))
            canteen.appendChild(day)
        return canteen

    @classmethod
    def _buildCategoryTag(cls, name, data, output):
        # skip empty categories:
        if len(data) < 1:
            return None
        category = output.createElement('category')
        category.setAttribute('name', name)
        for meal in data:
            category.appendChild(cls._buildMealTag(meal, output))
        return category

    @staticmethod
    def _buildMealTag(mealData, output):
        name, notes, prices = mealData
        meal = output.createElement('meal')
        # add name
        nametag = output.createElement('name')
        nametag.appendChild(output.createTextNode(name))
        meal.appendChild(nametag)
        # add notes:
        for note in notes:
            notetag = output.createElement('note')
            notetag.appendChild(output.createTextNode(note))
            meal.appendChild(notetag)
        # add prices:
        for role in prices:
            price = output.createElement('price')
            price.setAttribute('role', role)
            price.appendChild(output.createTextNode("{euros}.{cents:0>2}"
                              .format(euros=prices[role] // 100,
                                      cents=prices[role] % 100)))
            meal.appendChild(price)
        return meal


# Lazy version with auto extraction and convertion functions
# ----------------------------------------------------------


class LazyCanteen(BasicCanteen):
    """ asdf"""

    def __init__(self):
        super(LazyCanteen, self).__init__()
        self.legendData = None
        self.additionalCharges = (None, {})

    def setLegendData(self, *args, **kwargs):
        self.legendData = buildLegend(*args, **kwargs)

    def setAdditionalCharges(self, default, additional):
        """ This is a helper function, which fast up the calculation
            of prices. It is useable if the canteen has fixed
            additional charges for special roles.
            default specifies for which price role the price
            of addMeal are.
            additional is a dictonary which defines the extra
            costs (value) for other roles (key)."""
        self.additionalCharges = (default, buildPrices(additional))

    def addMeal(self, date, category, name, notes=[], prices={}, roles=None):
        if self.legendData:  # do legend extraction
            name, notes = extractNotes(name, notes, legend=self.legendData)
        prices = buildPrices(prices, roles,
                             default=self.additionalCharges[0],
                             additional=self.additionalCharges[1])
        super(LazyCanteen, self).addMeal(extractDate(date), category, name,
                                         notes, prices)

    @staticmethod
    def _handleDate(date):
        return extractDate(date)

OpenMensaCanteen = LazyCanteen
