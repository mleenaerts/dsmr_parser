import logging
import re

from PyCRC.CRC16 import CRC16

from dsmr_parser.objects import MBusObject, MBusObjectV2_2, CosemObject
from dsmr_parser.exceptions import ParseError, InvalidChecksumError

logger = logging.getLogger(__name__)


class TelegramParser(object):

    def __init__(self, telegram_specification,
                 enable_checksum_validation=False):
        """
        :param telegram_specification: determines how the telegram is parsed
        :type telegram_specification: dict
        """
        self.telegram_specification = telegram_specification
        self.enable_checksum_validation = enable_checksum_validation

    def parse(self, telegram_data):
        """
        Parse telegram from string to dict.

        The telegram str type makes python 2.x integration easier.

        :param str telegram: full telegram from start ('/') to checksum
            ('!ABCD') including line endings inbetween the telegram's lines
        :rtype: dict
        :returns: Shortened example:
            {
                ..
                r'0-0:96\.1\.1': <CosemObject>,  # EQUIPMENT_IDENTIFIER
                r'1-0:1\.8\.1': <CosemObject>,   # ELECTRICITY_USED_TARIFF_1
                r'0-\d:24\.3\.0': <MBusObject>,  # GAS_METER_READING
                ..
            }
        """

        if self.enable_checksum_validation:
            self.validate_checksum(telegram_data)

        telegram = {}

        for signature, parser in self.telegram_specification.items():
            match = re.search(signature, telegram_data, re.DOTALL)

            if match:
                telegram[signature] = parser.parse(match.group(0))

        return telegram

    @staticmethod
    def validate_checksum(telegram):
        """
        :param str telegram:
        :raises ParseError:
        :raises InvalidChecksumError:
        """

        # Extract the part for which the checksum applies.
        checksum_contents = re.search(r'\/.+\!', telegram, re.DOTALL)

        # Extract the hexadecimal checksum value itself.
        # The line ending '\r\n' for the checksum line can be ignored.
        checksum_hex = re.search(r'((?<=\!)[0-9A-Z]{4})+', telegram)

        if not checksum_contents or not checksum_hex:
            raise ParseError(
                'Failed to perform CRC validation because the telegram is '
                'incomplete. The checksum and/or content values are missing.'
            )

        calculated_crc = CRC16().calculate(checksum_contents.group(0))
        expected_crc = int(checksum_hex.group(0), base=16)

        if calculated_crc != expected_crc:
            raise InvalidChecksumError(
                "Invalid telegram. The CRC checksum '{}' does not match the "
                "expected '{}'".format(
                    calculated_crc,
                    expected_crc
                )
            )


class DSMRObjectParser(object):

    def __init__(self, *value_formats):
        self.value_formats = value_formats

    def _parse(self, line):
        # Match value groups, but exclude the parentheses
        pattern = re.compile(r'((?<=\()[0-9a-zA-Z\.\*]{0,}(?=\)))+')
        values = re.findall(pattern, line)

        # Convert empty value groups to None for clarity.
        values = [None if value == '' else value for value in values]

        if not values or len(values) != len(self.value_formats):
            raise ParseError("Invalid '%s' line for '%s'", line, self)

        return [self.value_formats[i].parse(value)
                for i, value in enumerate(values)]


class MBusParser(DSMRObjectParser):
    """
    Gas meter value parser.

    These are lines with a timestamp and gas meter value.

    Line format:
    'ID (TST) (Mv1*U1)'

     1   2     3   4

    1) OBIS Reduced ID-code
    2) Time Stamp (TST) of capture time of measurement value
    3) Measurement value 1 (most recent entry of buffer attribute without unit)
    4) Unit of measurement values (Unit of capture objects attribute)
    """

    def parse(self, line):
        values = self._parse(line)
        if len(values) == 2:
            return MBusObject(values)
        else:
            return MBusObjectV2_2(values)


class CosemParser(DSMRObjectParser):
    """
    Cosem object parser.

    These are data objects with a single value that optionally have a unit of
    measurement.

    Line format:
    ID (Mv*U)

    1  23  45

    1) OBIS Reduced ID-code
    2) Separator “(“, ASCII 28h
    3) COSEM object attribute value
    4) Unit of measurement values (Unit of capture objects attribute) – only if applicable
    5) Separator “)”, ASCII 29h
    """

    def parse(self, line):
        return CosemObject(self._parse(line))


class ProfileGenericParser(DSMRObjectParser):
    """
    Power failure log parser.

    These are data objects with multiple repeating groups of values.

    Line format:
    ID (z) (ID1) (TST) (Bv1*U1) (TST) (Bvz*Uz)

    1   2   3     4     5   6    7     8   9

    1) OBIS Reduced ID-code
    2) Number of values z (max 10).
    3) Identifications of buffer values (OBIS Reduced ID codes of capture objects attribute)
    4) Time Stamp (TST) of power failure end time
    5) Buffer value 1 (most recent entry of buffer attribute without unit)
    6) Unit of buffer values (Unit of capture objects attribute)
    7) Time Stamp (TST) of power failure end time
    8) Buffer value 2 (oldest entry of buffer attribute without unit)
    9) Unit of buffer values (Unit of capture objects attribute)
    """

    def parse(self, line):
        raise NotImplementedError()


class ValueParser(object):

    def __init__(self, coerce_type):
        self.coerce_type = coerce_type

    def parse(self, value):

        unit_of_measurement = None

        if value and '*' in value:
            value, unit_of_measurement = value.split('*')

        # A value group is not required to have a value, and then coercing does
        # not apply.
        value = self.coerce_type(value) if value is not None else value

        return {
            'value': value,
            'unit': unit_of_measurement
        }
