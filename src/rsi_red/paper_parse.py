"""PDF text worker, invoked in a bounded subprocess; never executes attachments."""
import io
import json
import logging
import sys


def main():
    from pypdf import PdfReader
    logging.disable(logging.CRITICAL)
    try:
        # Address space is capped on Linux; timeout is enforced by the parent on all platforms.
        if sys.platform.startswith('linux'):
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        body = sys.stdin.buffer.read(52428801)
        if len(body) > 52428800 or not body.startswith(b'%PDF-'):
            raise ValueError('invalid PDF')
        reader = PdfReader(io.BytesIO(body), strict=True)
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ValueError('unsupported PDF')
        pages, total = [], 0
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ''
            total += len(text)
            if total > 4000000:
                raise ValueError('text limit')
            pages.append({'page': i + 1, 'text': text, 'width': float(page.mediabox.width),
                          'height': float(page.mediabox.height)})
        json.dump({'pages': pages, 'parser': 'pypdf/6.12.0'}, sys.stdout)
    except Exception:
        sys.exit(2)


if __name__ == '__main__':
    main()
