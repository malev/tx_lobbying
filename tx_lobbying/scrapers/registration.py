"""
Scraper for Lobbyist Registration Forms.

The Excel formatted files can be obtained here:
http://www.ethics.state.tx.us/dfs/loblists.htm

Open and re-save as CSV.

"""
import json
import logging
import os
import sys

# don't use relative imports so this can also be run from the command line
from tx_lobbying.libs.address_normalizer import (
    clean_zipcode,
)
from tx_lobbying.models import (
    Address,
    Interest, Lobbyist, RegistrationReport,
    LobbyistAnnum, Compensation)
from tx_lobbying.scrapers.utils import (DictReader, convert_date_format_YMD)


logger = logging.getLogger(__name__)


def get_or_create_interest(row):
    """
    Update or create an `Interest`.

    Uses the name and state for uniquess. So we assume that AT&T Texas and AT&T
    DC are two separate interests, but AT&T Texas and AT & T Texas are the same.
    """
    address, __ = Address.objects.get_or_create(
        address1=row['EC_ADR1'],
        address2=row['EC_ADR2'],
        city=row['EC_CITY'],
        state=row['EC_STCD'],
        zipcode=clean_zipcode(row['EC_ZIP4']),
    )
    # TODO get other info from the csv
    defaults = dict(
        address=address,
    )
    interest, created = Interest.objects.get_or_create(
        name=row['CONCERNAME'],
        defaults=defaults,
    )
    return interest, address, created


def process_row(row, last_pass=None):
    report_date = convert_date_format_YMD(row['RPT_DATE'])
    year = row['YEAR_APPL']

    data = dict(
        address1=row['ADDRESS1'],
        address2=row['ADDRESS2'],
        city=row['CITY'],
        state=row['STATE'],
        zipcode=row['ZIPCODE'],
    )
    # HAHAHAHAHAHA
    if (last_pass and last_pass[0].address1 == data['address1']
            and last_pass[0].address2 == data['address2']
            and last_pass[0].city == data['city']
            and last_pass[0].state == data['state']
            and last_pass[0].zipcode == data['zipcode']):
        reg_address = last_pass[0]
    else:
        reg_address, created = Address.objects.get_or_create(**data)

    # Very basic `Lobbyist` info here, most of it actually comes from the
    # coversheets.
    if last_pass and last_pass[1].filer_id == int(row['FILER_ID']):
        lobbyist = last_pass[1]
    else:
        default_data = dict(
            name=row['LOBBYNAME'],
            sort_name=row['SORTNAME'],  # not LOB_SORT like in coversheets
            updated_at=report_date,
            address=reg_address,
        )
        lobbyist, created = Lobbyist.objects.update_or_create(
            filer_id=row['FILER_ID'],
            defaults=default_data)
        if created:
            logger.info("LOBBYIST: %s" % lobbyist)

    if row['CONCERNAME']:
        # interest/concern/client
        interest, interest_address, created = get_or_create_interest(row)
    else:
        interest_address = None
        interest = None

    # registration report
    if last_pass and last_pass[2].report_id == int(row['REPNO']):
        report = last_pass[2]
    else:
        default_data = dict(
            raw=json.dumps(row),
            report_date=report_date,
            year=year,
            address=reg_address,
        )
        report, created = RegistrationReport.objects.update_or_create(
            lobbyist=lobbyist,
            report_id=row['REPNO'],
            defaults=default_data)
        if created:
            logger.info("REPORT: %s" % report)

    if interest:
        # lobbyist M2M to `Interest` through `Compensation`
        annum, created = LobbyistAnnum.objects.update_or_create(
            lobbyist=lobbyist,
            year=year)
        # compensation
        default_data = dict(
            amount_high=int(round(float(row['NHIGH'] or "0"))),  # I hate myself
            amount_low=int(round(float(row['NLOW'] or "0"))),
            compensation_type=row['TYPECOPM'],
            address=interest_address,
            raw=json.dumps(row),
            updated_at=report_date,
        )
        if row['STARTDT']:
            default_data['start_date'] = row['STARTDT']
        if row['TERMDATE']:
            default_data['end_date'] = row['TERMDATE']
        # WISHLIST move this amount_guess logic into the model
        default_data['amount_guess'] = (default_data['amount_high'] +
            default_data['amount_low']) / 2
        Compensation.objects.update_or_create(
            annum=annum,
            interest=interest,
            defaults=default_data)
    return (reg_address, lobbyist, report)


def scrape(path, logger=logger):
    logger.info("Processing %s" % path)
    with open(path, 'rb') as f:
        reader = DictReader(f)
        last_pass = None
        for row in reader:
            last_pass = process_row(row, last_pass=last_pass)


def generate_test_row(path, **kwargs):
    """Helper to replace `scrape` to print out a sample for testing."""
    import random
    from pprint import pprint

    with open(path, 'rb') as f:
        reader = DictReader(f)
        for row in reader:
            if random.randint(0, 99) < 1:  # adjust this to go deeper
                pprint(row)
                break
# scrape = generate_test_row


if __name__ == "__main__":
    if len(sys.argv) < 2:
        exit("hey, I need a file:\n  %s <input>" % sys.argv[0])
    input_csv_path = sys.argv[1]
    if not os.path.isfile(input_csv_path):
        exit("hey, %s is not a file" % input_csv_path)
    scrape(input_csv_path)
