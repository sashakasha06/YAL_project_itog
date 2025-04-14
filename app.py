from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from all_models import db, User
import os
from imaplib import IMAP4_SSL
from email import message_from_string
from email.header import decode_header

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Конфигурация базы данных
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True  # Логирование SQL-запросов

# Создаем папку instance, если ее нет
os.makedirs(app.instance_path, exist_ok=True)

# Инициализация базы данных
db.init_app(app)

# Создаем таблицы при первом запуске
with app.app_context():
    db.create_all()
    print("Таблицы созданы")


def get_emails(username, imap_password):
    mail = IMAP4_SSL('imap.yandex.ru')
    print(username, imap_password)
    mail.login(username, imap_password)
    mail.select('inbox')

    # Получаем общее количество писем
    status, messages = mail.search(None, 'ALL')
    if status != 'OK':
        print("Ошибка при поиске писем")
        return []

    # Берем только последние 10 писем
    message_ids = messages[0].split()
    last_10_ids = message_ids[-10:] if len(message_ids) > 10 else message_ids

    emails = []
    for num in last_10_ids:
        status, data = mail.fetch(num, '(RFC822)')
        status, uid_data = mail.fetch(num, '(UID)')
        uid = uid_data[0].split()[2].decode('utf-8')
        print(status, uid)
        if status == 'OK':
            try:
                email_data = data[0][1].decode('utf-8')
                parsed_email = parse_email(email_data)
                emails.append(parsed_email)
            except Exception as e:
                print(f"Ошибка при обработке письма {num}: {str(e)}")

    return emails

    # Обратите внимание на отступ
    mail.logout()
    return []


def parse_email(email_data):
    msg = message_from_string(email_data)

    # Получаем отправителя
    from_ = msg.get('From', '')
    if from_:
        decoded = decode_header(from_)
        from_ = ''.join([str(t[0], t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0] for t in decoded])

    # Получаем тему
    subject = msg.get('Subject', '')
    if subject:
        decoded = decode_header(subject)
        subject = ''.join([str(t[0], t[1] or 'utf-8') if isinstance(t[0], bytes) else t[0] for t in decoded])

    # Получаем дату
    date = msg.get('Date', '')

    parsed_email = {
        'from': from_,
        'subject': subject,
        'date': date,
        'uid': msg.get('Message-Id', '')
    }
    return parsed_email


@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')


#

@app.route('/view_email/<email_id>')
def view_email(email_id):
    # Проверка авторизации
    if 'user' not in session:
        flash('Пожалуйста, авторизуйтесь', 'error')
        return redirect(url_for('login'))

    # Получаем пользователя из БД
    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()
        flash('Ваш аккаунт больше не существует', 'error')
        return redirect(url_for('login'))

    try:
        # Подключение к IMAP серверу
        with IMAP4_SSL('imap.yandex.ru') as mail:
            mail.login(user.username, user.imap_password)
            mail.select('inbox')

            # Получаем письмо
            status, data = mail.fetch(email_id, '(RFC822)')

            if status != 'OK' or not data or not data[0]:
                flash('Письмо не найдено', 'error')
                return redirect(url_for('dashboard'))

            # Обработка данных письма
            raw_email = data[0][1] if isinstance(data[0], tuple) else data[0]

            # Парсинг письма с обработкой кодировки
            try:
                msg = message_from_bytes(raw_email)
            except (TypeError, AttributeError):
                try:
                    msg = message_from_string(raw_email.decode('utf-8'))
                except UnicodeDecodeError:
                    msg = message_from_string(raw_email.decode('latin-1'))

            # Функция для декодирования MIME-заголовков
            def decode_header_text(header):
                if not header:
                    return None
                try:
                    decoded = decode_header(header)
                    return ''.join(
                        text.decode(encoding or 'utf-8', errors='replace') if isinstance(text, bytes) else text
                        for text, encoding in decoded
                    )
                except:
                    return header

            # Извлечение текста с улучшенной обработкой кодировки
            def get_email_text(message):
                if message.is_multipart():
                    for part in message.walk():
                        if part.get_content_type() == 'text/plain':
                            payload = part.get_payload(decode=True)
                            if payload:
                                try:
                                    return payload.decode('utf-8', errors='replace')
                                except UnicodeDecodeError:
                                    return payload.decode('latin-1', errors='replace')
                else:
                    payload = message.get_payload(decode=True)
                    if payload:
                        try:
                            return payload.decode('utf-8', errors='replace')
                        except UnicodeDecodeError:
                            return payload.decode('latin-1', errors='replace')
                return "Не удалось извлечь текст письма"

            # Получаем данные письма
            subject = decode_header_text(msg.get('Subject', 'Без темы'))
            from_email = decode_header_text(msg.get('From', 'Неизвестный отправитель'))
            text_content = get_email_text(msg)

            return render_template('simple_email.html',
                                   content=text_content,
                                   subject=subject,
                                   from_email=from_email,
                                   email_id=email_id)

    except Exception as e:
        app.logger.error(f'Ошибка при получении письма: {str(e)}', exc_info=True)
        flash('Произошла ошибка при обработке письма', 'error')
        return redirect(url_for('dashboard'))

@app.route('/distribution', methods=['GET', 'POST'])
def distribution():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        imap_password = request.form.get('imap_password', '').strip()
        phone = request.form.get('phone', '').strip()
        print(username, password, imap_password, phone)

        if not all([username, password, imap_password, phone]):
            flash('Все поля должны быть заполнены!', 'error')
            return redirect(url_for('register'))

        try:
            # Проверяем существование пользователя
            if User.query.filter_by(username=username).first():
                flash('Пользователь с таким логином уже существует!', 'error')
                return redirect(url_for('register'))

            # Создаем и сохраняем пользователя
            new_user = User(
                username=username,
                password=generate_password_hash(password),
                imap_password=imap_password,
                phone=phone
            )

            db.session.add(new_user)
            db.session.commit()

            # Проверяем, что пользователь добавлен
            if User.query.filter_by(username=username).first():
                flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
                return redirect(url_for('login'))
            else:
                raise Exception("Пользователь не был добавлен в БД")

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при регистрации: {str(e)}', 'error')
            app.logger.error(f'Registration error: {str(e)}')
        finally:
            db.session.close()

    return render_template('distribution.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not all([username, password]):
            flash('Все поля должны быть заполнены!', 'error')
            return redirect(url_for('login'))

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user'] = username
            flash('Вы успешно авторизовались!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Неверный логин или пароль', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user' in session:
        return redirect(url_for('dashboard'))

    return render_template('register.html')


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        flash('Пожалуйста, авторизуйтесь', 'error')
        return redirect(url_for('login'))

        # Проверяем, что пользователь существует в БД
    user = User.query.filter_by(username=session['user']).first()
    if not user:
        session.clear()  # Очищаем сессию если пользователь удален
        flash('Ваш аккаунт больше не существует', 'error')
        return redirect(url_for('login'))

    username = session['user']
    user = User.query.filter_by(username=username).first()
    if user:
        imap_password = user.imap_password
        emails = get_emails(username, imap_password)
        return render_template('dashboard.html', username=username, emails=emails)
    else:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Вы успешно вышли из системы', 'success')
    return redirect(url_for('home'))


@app.route('/debug/users')
def debug_users():
    users = User.query.all()
    return f"Всего пользователей: {len(users)}<br>{'<br>'.join(u.username for u in users)}"


if __name__ == '__main__':
    with app.app_context():
        # Проверяем существование таблицы
        inspector = db.inspect(db.engine)
        if 'users_info' not in inspector.get_table_names():
            db.create_all()
            print("Таблица users_info создана")
        else:
            print("Таблица users_info уже существует")

    app.run(debug=True)