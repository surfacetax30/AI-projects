import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.db.session import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_checklist_template_creation(db_session):
    from app.db.models import ChecklistTemplate

    template = ChecklistTemplate(
        part_type="金属支架",
        items=[
            {"code": "MAT-01", "name": "材质证明", "required": True},
            {"code": "DIM-01", "name": "尺寸报告", "required": True},
        ],
        version=1,
        is_active=True,
    )
    db_session.add(template)
    await db_session.commit()

    result = await db_session.execute(
        select(ChecklistTemplate).where(ChecklistTemplate.part_type == "金属支架")
    )
    saved = result.scalar_one()
    assert saved.part_type == "金属支架"
    assert len(saved.items) == 2
    assert saved.items[0]["code"] == "MAT-01"
    assert saved.is_active is True


@pytest.mark.asyncio
async def test_checklist_template_defaults(db_session):
    from app.db.models import ChecklistTemplate

    template = ChecklistTemplate(
        part_type="域控制器",
        items=[{"code": "EMC-01", "name": "EMC报告", "required": True}],
    )
    db_session.add(template)
    await db_session.commit()

    result = await db_session.execute(
        select(ChecklistTemplate).where(ChecklistTemplate.part_type == "域控制器")
    )
    saved = result.scalar_one()
    assert saved.version == 1
    assert saved.is_active is True