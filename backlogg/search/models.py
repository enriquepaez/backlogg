from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base


class CatalogSearchEntry(Base):
    """Read-only ORM mapping to the catalog_search materialized view.

    The view has no single-column primary key; (id, item_type) is the natural
    identity but ORM requires a PK declaration.  We use (id, item_type) as a
    composite PK to satisfy SQLAlchemy without misrepresenting the schema.
    search_vector is a tsvector column used only in raw SQL queries — it is not
    mapped here.
    """

    __tablename__ = "catalog_search"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    overview: Mapped[str | None] = mapped_column(String, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rating_external: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    rating_internal: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
