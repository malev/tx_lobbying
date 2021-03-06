"""

I'm too lazy to do unicode csv reading the "proper" way, so you're going to see
a lot of stupid .decode('latin_1') calls.

"""
from decimal import Decimal
import json
import logging
import os
import re

from django.utils.text import slugify

# don't use relative imports so this can also be run from the command line
from tx_lobbying.models import (Lobbyist,
    Coversheet, ExpenseDetailReport, Subject)
from tx_lobbying.scrapers.utils import (DictReader, convert_date_format,
    get_name_data, setfield)


# CONFIGURATION
YEAR_START = int(os.environ.get('YEAR_START') or 0)
TIME_FORMAT = '%a, %d %b %Y %H:%M:%S %Z'


logger = logging.getLogger(__name__)


def row_CVR(row, **kwargs):
    report_date = row['FILED_DATE'] or row['RPT_DATE']
    report_date = convert_date_format(report_date)

    # Lobbyist
    default_data = dict(
        updated_at=report_date)
    default_data.update(get_name_data(row))
    lobbyist, dirty = Lobbyist.objects.get_or_create(
        filer_id=row['FILER_ID'],
        defaults=default_data, )
    if report_date > lobbyist.updated_at:
        for key, value in default_data.items():
            setfield(lobbyist, key, value)
    if getattr(lobbyist, '_is_dirty', None):
        logger.debug(lobbyist._is_dirty)
        lobbyist.save()
        del lobbyist._is_dirty
        dirty = True
    if dirty:
        logger.info("LOBBYIST: %s" % lobbyist)

    # Coversheet
    default_data = dict(
        raw=json.dumps(row),
        lobbyist=lobbyist,
        report_date=report_date,
        correction=row['CORR_NUM'],
        year=row['YEAR_APPL'],
        transportation=row['EXTYP_TRAN'] or "0.00",
        food=row['EXTYP_FOOD'] or "0.00",
        entertainment=row['EXTYP_GIFT'] or "0.00",
        gifts=row['EXTYP_GIFT'] or "0.00",
        awards=row['EXTYP_AWDS'] or "0.00",
        events=row['EXTYP_EVNT'] or "0.00",
        media=row['EXTYP_MEDA'] or "0.00",
        ben_senators=row['EXBEN_SEN'] or "0.00",
        ben_representatives=row['EXBEN_REP'] or "0.00",
        ben_other=row['EXBEN_OTH'] or "0.00",
        ben_legislative=row['EXBEN_LEG'] or "0.00",
        ben_executive=row['EXBEN_EXEC'] or "0.00",
        ben_family=row['EXBEN_FAM'] or "0.00",
        ben_events=row['EXBEN_EVNT'] or "0.00",
        ben_guests=row['EXBEN_GUES'] or "0.00",
    )
    total_spent = sum(float(y or 0) for x, y in row.items() if x.startswith("EXTYP"))
    total_benefited = sum(float(y or 0) for x, y in row.items() if x.startswith("EXBEN"))
    default_data['total_spent'] = total_spent
    default_data['total_benefited'] = total_benefited
    default_data['spent_guess'] = max(total_spent, total_benefited)

    cover, dirty = Coversheet.objects.get_or_create(
        report_id=row['REPNO'],
        defaults=default_data, )
    if report_date > cover.report_date:
        for key, value in default_data.items():
            setfield(cover, key, value)
    if getattr(cover, '_is_dirty', None):
        logger.debug(cover._is_dirty)
        cover.save()
        del cover._is_dirty
        dirty = True
    if dirty:
        logger.info(u'COVER:    {} {} {}'
            .format(cover.report_date, cover.lobbyist, cover.report_id))
    return (lobbyist, cover)


def row_Detail(row, type, **kwargs):
    try:
        lobbyist = Lobbyist.objects.get(
            filer_id=row['FILER_ID'])
        cover = Coversheet.objects.get(report_id=row['REPNO'])
    except Lobbyist.DoesNotExist:
        logger.error('missing lobbyist {FILER_ID}'.format(**row))
        return
    except Coversheet.DoesNotExist:
        logger.error('missing cover sheet {REPNO}'.format(**row))
        return

    # ExpenseDetailreport
    amount = Decimal(row['EXPAMOUNT']) if row['EXPAMOUNT'] and row['EXPAMOUNT'] != '0' else None
    default_data = dict(
        cover=cover,
        lobbyist=lobbyist,
        year=int(row['YEAR_APPL']),
        raw=json.dumps(row),
    )

    if amount is None:
        default_data['amount'] = None  # force this to null
        default_data['amount_guess'] = Decimal((Decimal(row['nLow']) +
            Decimal(row['nHigh'])) / 2).quantize(Decimal('.01'))
    else:
        default_data['amount'] = default_data['amount_guess'] = amount
    report, dirty = ExpenseDetailReport.objects.get_or_create(
        idno=row['IDNO'], type=type,
        defaults=default_data)
    if not dirty:
        for key, value in default_data.items():
            setfield(report, key, value)
    if getattr(report, '_is_dirty', None):
        logger.debug(report._is_dirty)
        report.save()
        del report._is_dirty
        dirty = True
    if dirty:
        logger.info("Detail: %s" % report)


def row_LaSub(row, last_pass=None):
    """
    Each Coversheet is associated with subject matter.

    Data starts in 2000

    Snippets:

        from tx_lobbying.scrapers.expenses import generate_test_row
        generate_test_row('data/expenses/LaSub.csv')

        from tx_lobbying.scrapers.expenses import process_csv, row_LaSub
        process_csv('data/expenses/LaSub.csv', row_LaSub)

        import csv
        with open('subjects.csv', 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['Description'])
            for subject in Subject.objects.filter(category_id=84):
                writer.writerow([subject.other_description])
    """
    if int(row['CATGNUM']) == 84:
        # category id isn't unique if it is "other"
        defaults = dict(
            description=row['CATG_TEXT'],
            other_description=row['OTH_DESC'],
        )
        defaults['name'] = defaults['other_description']
        slug = slugify(unicode(defaults['other_description'] or 'other'))
        subject, created = Subject.objects.get_or_create(
            category_id=row['CATGNUM'],
            slug=slug,
            defaults=defaults,
        )
    else:
        defaults = dict(
            description=row['CATG_TEXT'],
            other_description=row['OTH_DESC'],
        )
        defaults['name'] = defaults['description'].title()
        defaults['slug'] = slugify(unicode(defaults['description']))
        subject, created = Subject.objects.get_or_create(
            category_id=row['CATGNUM'],
            defaults=defaults)
    if last_pass and last_pass[0].report_id == int(row['REPNO']):
        cover = last_pass[0]
    else:
        try:
            cover = Coversheet.objects.get(report_id=row['REPNO'])
        except Coversheet.DoesNotExist:
            logger.warn('No matching coversheet found {}'.format(row['REPNO']))
            return
    cover.subjects.add(subject)
    return (cover, subject)


def process_csv(path, _inner_func, **kwargs):
    logger.info("Processing %s" % path)
    total = get_record_count(path)
    with open(path, 'rb') as f:
        reader = DictReader(f, encoding='latin_1')
        # store output from the last pass since coversheet and lobbyist don't
        # really change row to row to save some queries.
        last_pass = None
        for i, row in enumerate(reader):
            if not i % 1000:
                logger.info(u'{}/{} filed date: {} report date:{}'
                    .format(
                        i,
                        total,
                        row.get('FILED_DATE'),
                        row.get('RPT_DATE')
                    ))
            if YEAR_START and int(row['YEAR_APPL']) < YEAR_START:
                continue
            try:
                last_pass = _inner_func(row, last_pass=last_pass, **kwargs)
            except ValueError as e:
                logger.warn('Row missing data: %s, %s' % (row, e))
                continue


def generate_test_row(path, **kwargs):
    import random
    from pprint import pprint

    logger.info("Processing %s" % path)
    with open(path, 'rb') as f:
        reader = DictReader(f, encoding='latin_1')
        for i, row in enumerate(reader):
            if random.randint(0, 999) < 1:  # adjust this to go deeper
                pprint(row)
                break


def get_record_count(path):
    """Really Hacky."""
    working_dir, filename = os.path.split(path)
    csv_name = os.path.splitext(filename)[0]

    try:
        with open(os.path.join(working_dir, 'Read_Me.txt')) as f:
            lines = f.readlines()
            for line in lines:
                bits = re.split(r'\s+', line)
                if bits[1] == csv_name:
                    human_count = bits[3]
                    return int(human_count.replace(',', ''))
        return 0
    except Exception:  # XXX
        return 0


def main(working_dir, logging_level=None):
    if logging_level:
        logger.setLevel(logging_level)
    process_csv(os.path.join(working_dir, "LaCVR.csv"),
        _inner_func=row_CVR)
    process_csv(os.path.join(working_dir, "LaSub.csv"),
        _inner_func=row_LaSub)
    if YEAR_START:
        # skip detailed reports when doing an abbreviated import
        return
    process_csv(os.path.join(working_dir, "LaFood.csv"),
        _inner_func=row_Detail, type="food")
    process_csv(os.path.join(working_dir, "LaAwrd.csv"),
        _inner_func=row_Detail, type="award")
    process_csv(os.path.join(working_dir, "LaEnt.csv"),
        _inner_func=row_Detail, type="entertainment")
    process_csv(os.path.join(working_dir, "LaGift.csv"),
        _inner_func=row_Detail, type="gift")
