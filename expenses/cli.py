"""`flask expenses ...` commands."""
import click

from auth.models import db
from expenses import expenses_bp
from expenses import models  # noqa: F401 — register tables


@expenses_bp.cli.command('init-db')
def init_db():
    """Create the expense tables (safe to re-run; existing tables are untouched)."""
    db.create_all()
    click.echo('Expense tables created.')


@expenses_bp.cli.command('seed-categories')
def seed_categories():
    """Add the starter expense categories mapped to QuickBooks accounts."""
    from expenses.seed import seed
    changed = seed()
    click.echo(f'Added/updated {len(changed)} categories'
               + (': ' + ', '.join(changed) if changed else '.'))


@expenses_bp.cli.command('add-show')
@click.argument('name')
@click.option('--season', required=True, help='e.g. 2026-27')
@click.option('--qb-class', default=None, help='QuickBooks class (defaults to the show name)')
@click.option('--producer', 'producers', multiple=True, help='Producer email (repeatable)')
def add_show(name, season, qb_class, producers):
    """Add a show NAME for SEASON (safe to re-run: existing shows get any new producers)."""
    name, season = name.strip(), season.strip()
    show = models.ExpenseShow.query.filter_by(name=name, season=season).first()
    if show is None:
        show = models.ExpenseShow(name=name, season=season, qb_class=(qb_class or name).strip())
        db.session.add(show)
        click.echo(f'Added {name} ({season}), QB class "{show.qb_class}".')
    else:
        click.echo(f'{name} ({season}) already exists.')
    for email in producers:
        email = email.lower().strip()
        if email not in show.producer_emails:
            show.producers.append(models.ExpenseShowProducer(email=email))
            click.echo(f'  producer: {email}')
    db.session.commit()


@expenses_bp.cli.command('grant')
@click.argument('email')
@click.argument('role', type=click.Choice(list(models.ROLES)))
def grant(email, role):
    """Give EMAIL an expense ROLE (vp_finance or president)."""
    email = email.lower().strip()
    if not models.ExpenseRole.query.filter_by(email=email, role=role).first():
        db.session.add(models.ExpenseRole(email=email, role=role))
        db.session.commit()
    click.echo(f'{email} is now {models.ROLES[role]}.')
