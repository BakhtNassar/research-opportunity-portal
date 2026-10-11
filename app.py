"""Research Opportunity Portal: Flask REST API backed exclusively by MySQL."""
import os
import re
from datetime import date
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

load_dotenv(Path(__file__).with_name('.env'))
app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
FIELDS = ('title', 'description', 'research_area', 'faculty_name', 'department',
          'required_skills', 'available_positions', 'application_deadline', 'status')
LIMITS = {'title': 200, 'description': 5000, 'research_area': 120,
          'faculty_name': 120, 'department': 120, 'required_skills': 2000}


def connect_db():
    return pymysql.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'), port=int(os.getenv('DB_PORT', '3306')),
        user=os.getenv('DB_USER', 'root'), password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'research_portal'), charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
        read_timeout=10, write_timeout=10,
    )


def serialize(row):
    if row is not None:
        row = dict(row)
        row['application_deadline'] = row['application_deadline'].isoformat()
    return row


def validate(data):
    if not isinstance(data, dict):
        return None, {'body': 'Send a JSON object with all required fields.'}
    cleaned, errors = {}, {}
    for field, limit in LIMITS.items():
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors[field] = 'This field is required and must be text.'
        elif len(value.strip()) > limit:
            errors[field] = f'Maximum length is {limit} characters.'
        else:
            cleaned[field] = value.strip()
    positions = data.get('available_positions')
    if type(positions) is not int or not 1 <= positions <= 10000:
        errors['available_positions'] = 'Use an integer between 1 and 10000.'
    else:
        cleaned['available_positions'] = positions
    deadline = data.get('application_deadline')
    try:
        if not isinstance(deadline, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', deadline):
            raise ValueError
        parsed = date.fromisoformat(deadline)
        if parsed.year < 1000:
            raise ValueError
        cleaned['application_deadline'] = parsed
    except ValueError:
        errors['application_deadline'] = 'Use a real date in YYYY-MM-DD format (year 1000 or later).'
    status = data.get('status')
    if status not in ('Open', 'Closed'):
        errors['status'] = 'Status must be Open or Closed.'
    else:
        cleaned['status'] = status
    unknown = set(data) - set(FIELDS)
    if unknown:
        errors['unknown_fields'] = 'Unexpected fields: ' + ', '.join(sorted(unknown))
    return cleaned, errors


@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.get('/api/opportunities')
def list_opportunities():
    with connect_db() as db:
        with db.cursor() as cursor:
            cursor.execute('SELECT * FROM opportunities ORDER BY id DESC')
            rows = cursor.fetchall()
    return jsonify([serialize(row) for row in rows]), 200


@app.get('/api/opportunities/<int:opportunity_id>')
def get_opportunity(opportunity_id):
    with connect_db() as db:
        with db.cursor() as cursor:
            cursor.execute('SELECT * FROM opportunities WHERE id=%s', (opportunity_id,))
            row = cursor.fetchone()
    if row is None:
        return jsonify(error='Research opportunity not found.'), 404
    return jsonify(serialize(row)), 200


@app.post('/api/opportunities')
def create_opportunity():
    data, errors = validate(request.get_json(silent=True))
    if errors:
        return jsonify(error='Validation failed.', details=errors), 400
    with connect_db() as db:
        with db.cursor() as cursor:
            cursor.execute('INSERT INTO opportunities (' + ', '.join(FIELDS) +
                           ') VALUES (' + ', '.join(['%s'] * len(FIELDS)) + ')',
                           tuple(data[field] for field in FIELDS))
            new_id = cursor.lastrowid
            cursor.execute('SELECT * FROM opportunities WHERE id=%s', (new_id,))
            row = cursor.fetchone()
        db.commit()
    response = jsonify(serialize(row))
    response.headers['Location'] = f'/api/opportunities/{new_id}'
    return response, 201


@app.put('/api/opportunities/<int:opportunity_id>')
def update_opportunity(opportunity_id):
    data, errors = validate(request.get_json(silent=True))
    if errors:
        return jsonify(error='Validation failed.', details=errors), 400
    with connect_db() as db:
        with db.cursor() as cursor:
            cursor.execute('SELECT id FROM opportunities WHERE id=%s FOR UPDATE', (opportunity_id,))
            if cursor.fetchone() is None:
                return jsonify(error='Research opportunity not found.'), 404
            cursor.execute('UPDATE opportunities SET ' + ', '.join(f'{f}=%s' for f in FIELDS) +
                           ' WHERE id=%s', tuple(data[f] for f in FIELDS) + (opportunity_id,))
            cursor.execute('SELECT * FROM opportunities WHERE id=%s', (opportunity_id,))
            row = cursor.fetchone()
        db.commit()
    return jsonify(serialize(row)), 200


@app.delete('/api/opportunities/<int:opportunity_id>')
def delete_opportunity(opportunity_id):
    with connect_db() as db:
        with db.cursor() as cursor:
            cursor.execute('DELETE FROM opportunities WHERE id=%s', (opportunity_id,))
            found = cursor.rowcount
        db.commit()
    if not found:
        return jsonify(error='Research opportunity not found.'), 404
    return jsonify(message='Research opportunity deleted.'), 200


@app.errorhandler(Exception)
def handle_error(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code
    app.logger.exception('Request failed')
    return jsonify(error='Internal server error. Check the server console and database configuration.'), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5000')), debug=False)
