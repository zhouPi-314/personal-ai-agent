"""link memory source to messages

Revision ID: 70aeb3383247
Revises: 4f1685aee84e
Create Date: 2026-10-20 18:41:29.834665

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70aeb3383247'
down_revision: Union[str, Sequence[str], None] = '4f1685aee84e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # uuid 无法直接转 bigint；该列当前全为 NULL，直接重建最安全。
    op.drop_column('memories', 'source_message_id')
    op.add_column('memories', sa.Column('source_message_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_memories_source_message_id',
        'memories',
        'messages',
        ['source_message_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_memories_source_message_id', 'memories', type_='foreignkey')
    op.drop_column('memories', 'source_message_id')
    op.add_column('memories', sa.Column('source_message_id', sa.UUID(), nullable=True))
