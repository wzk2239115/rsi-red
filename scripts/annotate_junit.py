"""Expose bounded CI test failures as check annotations without changing gate status."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def escape(value):
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


for name in sys.argv[1:]:
    path = Path(name)
    if not path.exists():
        print('::notice::JUnit report unavailable; inspect test process startup')
        continue
    for case in ET.parse(path).iter('testcase'):
        for failure in [*case.findall('failure'), *case.findall('error')]:
            title = escape(f"{case.get('classname')}.{case.get('name')}").replace(',', '%2C').replace(':', '%3A')
            message = escape((failure.text or failure.get('message', ''))[-8000:])
            print(f'::error title={title}::{message}')
