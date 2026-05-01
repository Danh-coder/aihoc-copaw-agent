from flask import Flask, request, jsonify
import os
import json
from math import sqrt

app = Flask(__name__)
DATA_FILE = '/data/vectors.json'
os.makedirs('/data', exist_ok=True)

try:
    with open(DATA_FILE, 'r') as f:
        STORAGE = json.load(f)
except Exception:
    STORAGE = {}


def save():
    with open(DATA_FILE, 'w') as f:
        json.dump(STORAGE, f)


@app.route('/vectors/upsert', methods=['POST'])
def upsert():
    payload = request.get_json() or {}
    vectors = payload.get('vectors', [])
    for v in vectors:
        vid = v.get('id')
        STORAGE[vid] = {'values': v.get('values'), 'metadata': v.get('metadata')}
    save()
    return jsonify({'status': 'ok', 'upserted': len(vectors)})


@app.route('/vectors/search', methods=['POST'])
def search():
    payload = request.get_json() or {}
    qvec = payload.get('vector')
    top_k = int(payload.get('top_k', 5))
    if not qvec:
        return jsonify({'matches': []})

    def score(vec):
        a = qvec
        b = vec
        # cosine similarity
        dot = sum(x * y for x, y in zip(a, b))
        na = sqrt(sum(x * x for x in a))
        nb = sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0
        return dot / (na * nb)

    matches = []
    for vid, item in STORAGE.items():
        s = score(item['values'])
        matches.append({'id': vid, 'score': s, 'metadata': item.get('metadata', {})})

    matches.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({'matches': matches[:top_k]})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
