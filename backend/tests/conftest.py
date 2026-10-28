"""Zajednička podešavanja testova: moduli koji učitavaju konfiguraciju traže master ključ (testovi ne koriste bazu)."""

import os

os.environ.setdefault("SMARTDISK_MASTER_KEY", "dGVzdC1rbGp1Yy1zYW1vLXphLXRlc3RvdmUtMzJiYWo=")
