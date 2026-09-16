"""Offline-only artifact validation entry point; no CAN path is exposed."""
import argparse
import json
from .artifacts import prepare_image


def main():
    parser = argparse.ArgumentParser(description='Validate a 320KiB firmware image entirely offline')
    parser.add_argument('image', help='320KiB vehicle firmware image')
    parser.add_argument('--start', type=lambda value: int(value, 0), default=0x18000)
    parser.add_argument('--end', type=lambda value: int(value, 0), default=0x4ffff)
    args = parser.parse_args()
    try:
        result = prepare_image(args.image, start_addr=args.start, end_addr=args.end)['metadata']
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Validation failed: {exc}\n')
    print(json.dumps(dict(result, status='validated', dry_run=True, boot_verified=False), indent=2))


if __name__ == '__main__':
    main()
