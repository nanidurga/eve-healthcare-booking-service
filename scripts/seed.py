"""Populate the database with a demo account and a small catalogue.

Idempotent: run it as often as you like. Existing rows are matched by their
natural keys (email, test code, centre name) and left alone.

    python -m scripts.seed
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionFactory, engine
from app.models.centre import Centre
from app.models.centre_test import CentreTest
from app.models.diagnostic_test import DiagnosticTest
from app.services import auth_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")

DEMO_EMAIL = "asha@example.com"
DEMO_PASSWORD = "password123"

TESTS = [
    ("CBC", "Complete Blood Count", "Screens for anaemia, infection and more.", None),
    ("LFT", "Liver Function Test", "Assesses liver enzymes and proteins.", "Fast for 8 hours."),
    ("TSH", "Thyroid Stimulating Hormone", "Screens thyroid function.", None),
    ("HBA1C", "Glycated Haemoglobin", "Average blood sugar over ~3 months.", None),
    ("LIPID", "Lipid Profile", "Cholesterol and triglycerides.", "Fast for 12 hours."),
    ("VITD", "Vitamin D (25-OH)", "Vitamin D deficiency screen.", None),
]

CENTRES = [
    ("EVE Diagnostics - Banjara Hills", "Hyderabad", "Road No. 12, Banjara Hills", "+914023551200"),
    ("EVE Diagnostics - Gachibowli", "Hyderabad", "Survey No. 64, Gachibowli", "+914023551201"),
    ("EVE Diagnostics - Koramangala", "Bengaluru", "80 Feet Road, 4th Block", "+918041551202"),
]

# centre name -> {test code: price}. The same test is priced differently per
# centre on purpose -- that is why price lives on the offering.
PRICING = {
    "EVE Diagnostics - Banjara Hills": {
        "CBC": "450.00", "LFT": "999.13", "TSH": "550.00", "LIPID": "899.00"
    },
    "EVE Diagnostics - Gachibowli": {
        "CBC": "399.00", "TSH": "520.00", "HBA1C": "650.00", "VITD": "1450.00"
    },
    "EVE Diagnostics - Koramangala": {
        "CBC": "525.00", "LIPID": "950.00", "HBA1C": "699.00"
    },
}


async def seed() -> None:
    async with SessionFactory() as session:
        existing_user = await auth_service.get_user_by_email(session, DEMO_EMAIL)
        if existing_user is None:
            await auth_service.register_user(
                session,
                email=DEMO_EMAIL,
                password=DEMO_PASSWORD,
                full_name="Asha Verma",
                phone="+919876543210",
            )
            logger.info("Created demo user %s (password: %s)", DEMO_EMAIL, DEMO_PASSWORD)
        else:
            logger.info("Demo user %s already exists", DEMO_EMAIL)

        tests: dict[str, DiagnosticTest] = {}
        for code, name, description, preparation in TESTS:
            test = await session.scalar(
                select(DiagnosticTest).where(DiagnosticTest.code == code)
            )
            if test is None:
                test = DiagnosticTest(
                    code=code, name=name, description=description, preparation=preparation
                )
                session.add(test)
            tests[code] = test
        await session.flush()

        centres: dict[str, Centre] = {}
        for name, city, address, phone in CENTRES:
            centre = await session.scalar(select(Centre).where(Centre.name == name))
            if centre is None:
                centre = Centre(name=name, city=city, address=address, phone=phone)
                session.add(centre)
            centres[name] = centre
        await session.flush()

        created = 0
        for centre_name, prices in PRICING.items():
            centre = centres[centre_name]
            for code, price in prices.items():
                test = tests[code]
                exists = await session.scalar(
                    select(CentreTest).where(
                        CentreTest.centre_id == centre.id, CentreTest.test_id == test.id
                    )
                )
                if exists is None:
                    session.add(
                        CentreTest(
                            centre_id=centre.id,
                            test_id=test.id,
                            price=Decimal(price),
                        )
                    )
                    created += 1

        await session.commit()
        logger.info(
            "Seeded %d tests, %d centres, %d new offerings",
            len(TESTS),
            len(CENTRES),
            created,
        )
        logger.info(
            "Note: the LFT offering at Banjara Hills is priced 999.13 so the "
            "simulated gateway declines it -- useful for exercising the FAILED path."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
