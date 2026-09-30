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
