"""A mako template for creating Alembic migration scripts.

This template is the default script chosen by the 'alembic revision'
command.

It may be modified directly, or a new template added to the
'alembic/versions' directory to be used with the '--template' option
to 'alembic revision'.

"""
from alembic.ddl.impl import DefaultImpl
from alembic.operations import ops
from alembic.runtime.environment import MigrationContext
from alembic.util import InspectionClassName


${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    ${upgrades}


def downgrade():
    ${downgrades}
