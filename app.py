from flask import Flask, render_template, url_for, request, redirect, flash,jsonify, session, Response
import os
import cv2
import pygame
import mysql.connector
from flask_mysqldb import MySQL
from datetime import datetime, timedelta
import time
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from ultralytics import YOLO
from twilio.rest import Client
from dotenv import load_dotenv
from config import config

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'mp4', 'avi', 'mov', 'mkv'}
app.secret_key = 'your_secret_key'  # Replace with a secure key

# Load the trained model
model = YOLO('static/model/fix.pt')

# Initialize Pygame for sound playback
pygame.mixer.init()
alarm_sound = 'static/alarm/alarm_sound.mp3'  # Path to the alarm sound file
pygame.mixer.music.load(alarm_sound)

# Global variables
cap = None
alarm_playing = False
drowning_detected = False
current_source = None
detected_persons = set()
drowning_start_time = None
drowning_duration = 0

load_dotenv()

# Konfigurasi Twilio
ACCOUNT_SID = os.getenv('ACCOUNT_SID')
AUTH_TOKEN = os.getenv('AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
RECIPIENT_WHATSAPP_NUMBER = os.getenv('RECIPIENT_WHATSAPP_NUMBER')

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# MySQL database configuration
db_config = {
    'user': 'root',
    'password': '',
    'host': 'localhost',
    'database': 'drowning'
}

# Fungsi untuk mengirim pesan WhatsApp
def send_whatsapp_message(to, message):
    try:
        message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to
        )
        return message.sid
    except Exception as e:
        print(f"Error: {e}")
        return None


@app.route('/')
def index():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    source = request.args.get('source', '')
    return render_template('dashboard.html', source=source, alarm_duration=config.ALARM_DURATION)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def insert_drowning_event(detection_time, source_path, person_id, status):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        insert_query = """
        INSERT INTO drowning_events (detection_time, source_path, person_id, status)
        VALUES (%s, %s, %s, %s)
        """
        cursor.execute(insert_query, (detection_time, source_path, person_id, status))
        connection.commit()
    except mysql.connector.Error as err:
        print(f"Error: {err}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def generate_frames(source):
    global cap, alarm_playing, drowning_detected, current_source, drowning_start_time, drowning_duration

    if cap is not None:
        cap.release()  # Lepaskan capture video sebelumnya jika ada

    cap = cv2.VideoCapture(source)
    current_source = source

    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return

    detection_time = None  # Inisialisasi detection_time

    while True:
        if current_source != source:
            break

        ret, frame = cap.read()
        if not ret:
            print(f"Error: Failed to read frame from source {source}")
            break

        # Resize frame ke 1080x600
        frame = cv2.resize(frame, (1080, 600))

        # Lakukan deteksi dan tracking
        results = model.track(frame)

        # Reset flag deteksi tenggelam
        drowning_detected = False

        # Tampilkan hasil pada frame
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                class_id = int(box.cls[0])
                conf = float(box.conf[0])
                obj_id = int(box.id[0]) if box.id is not None else -1
                # Hapus kepercayaan dari label
                label = f"{result.names[class_id]} ID:{obj_id}"

                # Atur warna bounding box default (biru) untuk berenang
                if result.names[class_id] == "swimming":
                    color = (255, 0, 0)  # Biru
                else:
                    color = (0, 0, 255)  # Merah untuk tenggelam
                    drowning_detected = True

                    # Masukkan ke database hanya jika obj_id valid (bukan -1) dan belum terdeteksi
                    if obj_id != -1 and obj_id not in detected_persons:
                        detection_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        detected_persons.add(obj_id)
                        insert_drowning_event(detection_time, source, obj_id, 'drowning')
                        print(f"Drowning event detected. Person ID: {obj_id}")

                # Gambar bounding box dan label
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                # Tambahkan timer ke label jika tenggelam terdeteksi
                if drowning_detected:
                    if drowning_start_time is None:
                        drowning_start_time = time.time()  # Mulai timer
                    else:
                        drowning_duration = time.time() - drowning_start_time  # Update durasi
                    label += f" Timer: {int(drowning_duration)}s"

                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Kontrol alarm berdasarkan deteksi tenggelam
        if drowning_detected:
            if drowning_duration > config.ALARM_DURATION and not alarm_playing:
                pygame.mixer.music.play(-1)  # Mainkan suara alarm tanpa henti
                alarm_playing = True

                # Kirim notifikasi WhatsApp hanya jika detection_time telah diinisialisasi
                if detection_time:
                    message = f"Terdeteksi tenggelam!\nWaktu: {detection_time}\nSource: {source}\nPerson ID: {obj_id}"
                    send_whatsapp_message(RECIPIENT_WHATSAPP_NUMBER, message)
        else:
            drowning_start_time = None
            drowning_duration = 0
            detection_time = None  # Reset detection_time ketika tidak ada deteksi tenggelam
            if alarm_playing:
                pygame.mixer.music.stop()  # Hentikan suara alarm
                alarm_playing = False

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()

    

@app.route('/ip_camera_feed', methods=['POST'])
def ip_camera_feed():
    global cap, current_source
    ip_url = request.form.get('ip_url')
    if ip_url:
        print(f"Received IP URL: {ip_url}")  # Debugging: print the received IP URL
        if cap is not None:
            cap.release()  # Release the previous video capture if exists
        current_source = ip_url
        return redirect(url_for('dashboard', source=ip_url))
    return redirect('/')


# Tambahkan rute untuk menangani perubahan durasi alarm
@app.route('/set_alarm_duration', methods=['POST'])
def set_alarm_duration():
    try:
        config.ALARM_DURATION = int(request.form['alarm_duration'])
        flash('Alarm duration updated successfully!', 'success')
    except ValueError:
        flash('Invalid input for alarm duration. Please enter a valid number.', 'danger')
    return redirect(url_for('dashboard'))



@app.route('/reset', methods=['POST'])
def reset():
    global cap, alarm_playing, drowning_detected, drowning_start_time, drowning_duration
    if cap is not None:
        cap.release()  # Release the current video capture if exists
    cap = None
    alarm_playing = False
    drowning_detected = False
    drowning_start_time = None
    drowning_duration = 0
    pygame.mixer.music.stop()  # Stop the alarm if it's playing
    flash('System reset successfully!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/video_feed')
def video_feed():
    source = request.args.get('source', '')
    print(f"Video feed source: {source}")  # Debugging: print the video feed source
    if source:
        return Response(generate_frames(source), mimetype='multipart/x-mixed-replace; boundary=frame')
    return "No video source provided."

@app.route('/upload_video', methods=['POST'])
def upload_video():
    global current_source
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    if file and allowed_file(file.filename):
        # Clear all files in the uploads folder before saving new file
        if cap is not None:
            cap.release()  # Release the previous video capture if exists
            cv2.destroyAllWindows()  # Close any OpenCV windows if open
            
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except PermissionError as e:
                    print(f"Could not remove file {file_path}: {e}")

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        current_source = filepath
        return redirect(url_for('dashboard', source=filepath))
    return redirect(request.url)

@app.route('/account')
def account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('account.html')

@app.route('/charts')
def charts():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('charts.html')


# Function to get the start of the week (Monday)
def get_start_of_week():
    today = datetime.today()
    start = today - timedelta(days=today.weekday())
    return start

# Function to generate list of days for the current week
def get_days_of_week():
    start = get_start_of_week()
    return [(start + timedelta(days=i)).strftime('%A, %d %B %Y') for i in range(7)]

# Route to fetch drowning events per day for the selected date range
@app.route('/api/drowning_events_per_day', methods=['GET'])
def get_drowning_events_per_day():
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor(dictionary=True)

        # Get start_date and end_date from query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # If start_date or end_date are not provided, default to current week
        if not start_date or not end_date:
            start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=6 - datetime.now().weekday())).strftime('%Y-%m-%d')

        # Query to get count of drowning events per day for the specified date range
        query = """
                SELECT DATE_FORMAT(detection_time, '%Y-%m-%d') AS event_day, COUNT(*) AS count
                FROM drowning_events
                WHERE detection_time BETWEEN %s AND %s
                GROUP BY DATE_FORMAT(detection_time, '%Y-%m-%d')
                ORDER BY event_day
                """

        cursor.execute(query, (start_date, end_date))
        results = cursor.fetchall()

        # Create labels and data for chart
        labels = []
        data = []
        for row in results:
            labels.append(row['event_day'])
            data.append(row['count'])

        return jsonify({'labels': labels, 'data': data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
            
@app.route('/histori')
def histori():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("SELECT id, detection_time, person_id, status FROM drowning_events")
        events = cursor.fetchall()
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        events = []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
    
    return render_template('histori.html', events=events)



@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        try:
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor()
            insert_query = """
            INSERT INTO users (name, email, password)
            VALUES (%s, %s, %s)
            """
            cursor.execute(insert_query, (name, email, hashed_password))
            connection.commit()
            flash('User registered successfully!', 'success')
            return redirect(url_for('login'))
        except mysql.connector.Error as err:
            print(f"Error: {err}")
            flash('Failed to register user.', 'danger')
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    
    return render_template('signup.html')


# Route untuk menampilkan daftar pengguna (orders)
@app.route('/orders', methods=['GET', 'POST'])
def orders():
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    
    if request.method == 'POST':
        user_id = request.form['id']
        new_name = request.form['name']
        new_email = request.form['email']
        cursor.execute("UPDATE users SET name=%s, email=%s WHERE id=%s", (new_name, new_email, user_id))
        connection.commit()
        flash('User updated successfully', 'success')

    cursor.execute('SELECT id, name, email FROM users')
    users = cursor.fetchall()
    cursor.close()
    connection.close()
    return render_template('orders.html', users=users)


# Route untuk edit pengguna
@app.route('/edit_user/<int:user_id>', methods=['GET'])
def edit_user(user_id):
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT id, name, email FROM users WHERE id = %s", [user_id])
    user = cursor.fetchone()
    cursor.close()
    connection.close()
    return render_template('orders.html', user=user)  # Render the same orders.html with edit form

# Route for adding a new user
@app.route('/add_user', methods=['POST'])
def add_user():
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    hashed_password = generate_password_hash(password)  # Hash the password before storing it

    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, hashed_password))
    connection.commit()
    cursor.close()
    connection.close()

    flash('Admin user added successfully', 'success')
    return redirect(url_for('orders'))


# Route untuk delete pengguna
@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor(dictionary=True)
    cursor.execute("DELETE FROM users WHERE id = %s", [user_id])
    connection.commit()
    cursor.close()
    connection.close()
    flash('User deleted successfully', 'success')
    return redirect(url_for('orders'))



@app.route('/logout')
def logout():
    session.clear()
    if cap is not None:
        cap.release()  # Release the current video capture if exists
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        
        try:
            connection = mysql.connector.connect(**db_config)
            cursor = connection.cursor()
            cursor.execute("SELECT id, name, password FROM users WHERE name = %s", (name,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['user_name'] = user[1]
                flash('Login successful!', 'success')
                return redirect(url_for('login'))  # Redirect back to the login page to trigger SweetAlert
            else:
                flash('Invalid name or password.', 'danger')
        except mysql.connector.Error as err:
            print(f"Error: {err}")
            flash('Failed to login.', 'danger')
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    
    return render_template('login.html')


if __name__ == "__main__":
    app.run(debug=True)
