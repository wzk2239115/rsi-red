"""External stdlib harness fixture; scores come from fake checkpoints, not inference."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--mode', default='valid')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.mode == 'sleep':
        time.sleep(60)
    if args.mode == 'exit':
        raise SystemExit(7)
    model = json.loads((Path(config['bindings']['model_path']) / 'config.json').read_text())
    rows = [json.loads(line) for line in Path(config['bindings']['input_path']).read_text().splitlines()]
    texts = model.get('fixture_predictions', ['fixture prediction'] * len(rows))
    predictions = [{'id': row['id'], 'task': row['task'], 'prediction': texts[index],
                    'score': model['fixture_scores'][index], 'finish_reason': 'stop'}
                   for index, row in enumerate(rows)]
    if args.mode == 'missing':
        predictions.pop()
    elif args.mode == 'duplicate':
        predictions.append(predictions[0])
    elif args.mode == 'unknown':
        predictions[0]['id'] = 'unregistered-question'
    elif args.mode == 'nan':
        predictions[0]['score'] = float('nan')
    output = Path(config['bindings']['output_path'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('broken json' if args.mode == 'badjson' else
                      ''.join(json.dumps(row) + '\n' for row in predictions))
    print('external fixture completed', flush=True)


if __name__ == '__main__':
    main()
