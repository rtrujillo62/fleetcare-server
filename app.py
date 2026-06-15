from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fleetcare-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///fleetcare.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─── MODELOS ───────────────────────────────────────────────

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), default='usuario')  # 'admin' o 'usuario'
    activo = db.Column(db.Boolean, default=True)
    creado = db.Column(db.DateTime, default=datetime.utcnow)
    vehiculos = db.relationship('Vehiculo', backref='propietario', lazy=True)

class Vehiculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    anio = db.Column(db.Integer)
    placa = db.Column(db.String(20))
    vin = db.Column(db.String(17))
    tipo = db.Column(db.String(20))
    combustible = db.Column(db.String(20))
    color = db.Column(db.String(30))
    odometro = db.Column(db.Float, default=0)
    kml_esperado = db.Column(db.Float)
    ultimo_servicio_fecha = db.Column(db.Date)
    ultimo_servicio_odo = db.Column(db.Float)
    intervalos = db.Column(db.Text, default='{}')  # JSON
    creado = db.Column(db.DateTime, default=datetime.utcnow)
    servicios = db.relationship('Servicio', backref='vehiculo', lazy=True)
    combustibles = db.relationship('RegistroCombustible', backref='vehiculo', lazy=True)
    documentos = db.relationship('Documento', backref='vehiculo', lazy=True)
    lecturas_odo = db.relationship('LecturaOdo', backref='vehiculo', lazy=True)

class Servicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculo.id'), nullable=False)
    tarea_id = db.Column(db.String(30), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    odometro = db.Column(db.Float)
    costo = db.Column(db.Float)
    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class RegistroCombustible(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculo.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    odometro = db.Column(db.Float)
    litros = db.Column(db.Float)
    costo = db.Column(db.Float)
    precio_litro = db.Column(db.Float)
    tanque_lleno = db.Column(db.Boolean, default=True)
    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class LecturaOdo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculo.id'), nullable=False)
    odometro = db.Column(db.Float)
    fecha = db.Column(db.Date, nullable=False)
    fuente = db.Column(db.String(20))  # servicio, combustible, manual
    creado = db.Column(db.DateTime, default=datetime.utcnow)

class Documento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculo.id'), nullable=False)
    tipo = db.Column(db.String(50))  # placa, seguro, revision, licencia
    descripcion = db.Column(db.String(100))
    vencimiento = db.Column(db.Date)
    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

# ─── HELPERS ───────────────────────────────────────────────

def login_requerido(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_requerido(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario_id' not in session:
            return redirect(url_for('login'))
        u = Usuario.query.get(session['usuario_id'])
        if not u or u.rol != 'admin':
            return redirect(url_for('dashboard_usuario'))
        return f(*args, **kwargs)
    return decorated

def usuario_actual():
    if 'usuario_id' in session:
        return Usuario.query.get(session['usuario_id'])
    return None

TAREAS = [
    {'id':'oil','nombre':'Cambio de aceite','km':5000,'meses':6},
    {'id':'air','nombre':'Filtro de aire','km':15000,'meses':12},
    {'id':'fuel','nombre':'Filtro de combustible','km':30000,'meses':24},
    {'id':'cabin','nombre':'Filtro de cabina','km':20000,'meses':12},
    {'id':'tires','nombre':'Rotación de llantas','km':8000,'meses':6},
    {'id':'brakes','nombre':'Revisión de frenos','km':20000,'meses':12},
    {'id':'battery','nombre':'Revisión de batería','km':0,'meses':12},
    {'id':'coolant','nombre':'Líquido refrigerante','km':40000,'meses':24},
    {'id':'spark','nombre':'Bujías','km':40000,'meses':24},
    {'id':'timing','nombre':'Correa de distribución','km':80000,'meses':48},
    {'id':'trans','nombre':'Fluido de transmisión','km':60000,'meses':36},
    {'id':'align','nombre':'Alineación y balanceo','km':10000,'meses':12},
]

TIPOS_DOCUMENTO = [
    {'id':'placa','nombre':'Renovación de placas'},
    {'id':'seguro','nombre':'Vencimiento de seguro'},
    {'id':'revision','nombre':'Revisión técnica'},
    {'id':'licencia','nombre':'Licencia de conducir'},
    {'id':'otro','nombre':'Otro'},
]

def calcular_estado_tarea(vehiculo, tarea):
    intervalos = json.loads(vehiculo.intervalos or '{}')
    km_intervalo = intervalos.get(tarea['id']+'_km', tarea['km'])
    mo_intervalo = intervalos.get(tarea['id']+'_mo', tarea['meses'])

    ultimo_svc = Servicio.query.filter_by(
        vehiculo_id=vehiculo.id, tarea_id=tarea['id']
    ).order_by(Servicio.fecha.desc()).first()

    ultimo_km = ultimo_svc.odometro if ultimo_svc else (vehiculo.ultimo_servicio_odo or 0)
    ultima_fecha = ultimo_svc.fecha if ultimo_svc else (vehiculo.ultimo_servicio_fecha or date.today())

    meses_diff = (date.today() - ultima_fecha).days / 30.44
    km_diff = vehiculo.odometro - ultimo_km

    pct_km = km_diff / km_intervalo if km_intervalo > 0 else 0
    pct_mo = meses_diff / mo_intervalo if mo_intervalo > 0 else 0
    pct = min(max(pct_km, pct_mo), 1.0)

    if pct >= 1.0:
        estado = 'red'
    elif pct >= 0.85:
        estado = 'yellow'
    else:
        estado = 'green'

    proximo_km = ultimo_km + km_intervalo if km_intervalo > 0 else None
    return {'estado': estado, 'pct': pct, 'proximo_km': proximo_km}

def calcular_estado_documento(doc):
    if not doc.vencimiento:
        return 'green'
    dias = (doc.vencimiento - date.today()).days
    if dias < 0:
        return 'red'
    elif dias <= 30:
        return 'yellow'
    return 'green'

# ─── RUTAS AUTH ────────────────────────────────────────────

@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    u = Usuario.query.get(session['usuario_id'])
    if u and u.rol == 'admin':
        return redirect(url_for('dashboard_admin'))
    return redirect(url_for('dashboard_usuario'))

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        u = Usuario.query.filter_by(email=email, activo=True).first()
        if u and check_password_hash(u.password_hash, password):
            session['usuario_id'] = u.id
            session['nombre'] = u.nombre
            session['rol'] = u.rol
            if u.rol == 'admin':
                return redirect(url_for('dashboard_admin'))
            return redirect(url_for('dashboard_usuario'))
        error = 'Email o contraseña incorrectos'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── RUTAS ADMIN ───────────────────────────────────────────

@app.route('/admin')
@admin_requerido
def dashboard_admin():
    usuarios = Usuario.query.filter_by(rol='usuario').order_by(Usuario.nombre).all()
    total_vehiculos = Vehiculo.query.count()
    # Alertas globales
    alertas_red = 0
    alertas_yellow = 0
    for v in Vehiculo.query.all():
        for t in TAREAS:
            est = calcular_estado_tarea(v, t)
            if est['estado'] == 'red': alertas_red += 1
            elif est['estado'] == 'yellow': alertas_yellow += 1
        for d in v.documentos:
            est = calcular_estado_documento(d)
            if est == 'red': alertas_red += 1
            elif est == 'yellow': alertas_yellow += 1
    return render_template('admin_dashboard.html',
        usuarios=usuarios,
        total_vehiculos=total_vehiculos,
        alertas_red=alertas_red,
        alertas_yellow=alertas_yellow,
        usuario=usuario_actual()
    )

@app.route('/admin/usuarios', methods=['GET','POST'])
@admin_requerido
def admin_usuarios():
    if request.method == 'POST':
        nombre = request.form.get('nombre','').strip()
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        rol = request.form.get('rol','usuario')
        if nombre and email and password:
            if not Usuario.query.filter_by(email=email).first():
                u = Usuario(
                    nombre=nombre, email=email,
                    password_hash=generate_password_hash(password),
                    rol=rol
                )
                db.session.add(u)
                db.session.commit()
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    return render_template('admin_usuarios.html', usuarios=usuarios, usuario=usuario_actual())

@app.route('/admin/usuario/<int:uid>/toggle')
@admin_requerido
def toggle_usuario(uid):
    u = Usuario.query.get_or_404(uid)
    u.activo = not u.activo
    db.session.commit()
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/flota')
@admin_requerido
def admin_flota():
    vehiculos = Vehiculo.query.join(Usuario).order_by(Usuario.nombre).all()
    data = []
    for v in vehiculos:
        estados = [calcular_estado_tarea(v,t)['estado'] for t in TAREAS]
        doc_estados = [calcular_estado_documento(d) for d in v.documentos]
        todos = estados + doc_estados
        if 'red' in todos: estado = 'red'
        elif 'yellow' in todos: estado = 'yellow'
        else: estado = 'green'
        data.append({'vehiculo': v, 'estado': estado})
    return render_template('admin_flota.html', data=data, usuario=usuario_actual())

@app.route('/admin/vehiculo/<int:vid>')
@admin_requerido
def admin_vehiculo(vid):
    v = Vehiculo.query.get_or_404(vid)
    tareas_con_estado = [{'tarea':t, **calcular_estado_tarea(v,t)} for t in TAREAS]
    servicios = Servicio.query.filter_by(vehiculo_id=vid).order_by(Servicio.fecha.desc()).all()
    combustibles = RegistroCombustible.query.filter_by(vehiculo_id=vid).order_by(RegistroCombustible.fecha.desc()).all()
    lecturas = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.fecha.desc()).limit(10).all()
    documentos = Documento.query.filter_by(vehiculo_id=vid).all()
    docs_con_estado = [{'doc':d,'estado':calcular_estado_documento(d)} for d in documentos]
    return render_template('vehiculo_detalle.html',
        v=v, tareas=tareas_con_estado, servicios=servicios,
        combustibles=combustibles, lecturas=lecturas,
        docs=docs_con_estado, tipos_doc=TIPOS_DOCUMENTO,
        es_admin=True, usuario=usuario_actual()
    )

@app.route('/admin/documento/agregar', methods=['POST'])
@admin_requerido
def agregar_documento():
    vid = request.form.get('vehiculo_id')
    tipo = request.form.get('tipo')
    descripcion = request.form.get('descripcion','')
    vencimiento_str = request.form.get('vencimiento')
    notas = request.form.get('notas','')
    vencimiento = datetime.strptime(vencimiento_str, '%Y-%m-%d').date() if vencimiento_str else None
    doc = Documento(vehiculo_id=vid, tipo=tipo, descripcion=descripcion, vencimiento=vencimiento, notas=notas)
    db.session.add(doc)
    db.session.commit()
    return redirect(url_for('admin_vehiculo', vid=vid))

@app.route('/admin/documento/<int:did>/eliminar')
@admin_requerido
def eliminar_documento(did):
    doc = Documento.query.get_or_404(did)
    vid = doc.vehiculo_id
    db.session.delete(doc)
    db.session.commit()
    return redirect(url_for('admin_vehiculo', vid=vid))

# ─── RUTAS USUARIO ─────────────────────────────────────────

@app.route('/usuario')
@login_requerido
def dashboard_usuario():
    u = usuario_actual()
    if u.rol == 'admin':
        return redirect(url_for('dashboard_admin'))
    vehiculos = Vehiculo.query.filter_by(usuario_id=u.id).all()
    data = []
    for v in vehiculos:
        estados = [calcular_estado_tarea(v,t)['estado'] for t in TAREAS]
        doc_estados = [calcular_estado_documento(d) for d in v.documentos]
        todos = estados + doc_estados
        if 'red' in todos: estado = 'red'
        elif 'yellow' in todos: estado = 'yellow'
        else: estado = 'green'
        data.append({'vehiculo': v, 'estado': estado})
    return render_template('usuario_dashboard.html', data=data, usuario=u)

@app.route('/usuario/vehiculo/nuevo', methods=['GET','POST'])
@login_requerido
def nuevo_vehiculo():
    u = usuario_actual()
    if request.method == 'POST':
        v = Vehiculo(
            usuario_id=u.id,
            marca=request.form.get('marca',''),
            modelo=request.form.get('modelo',''),
            anio=request.form.get('anio'),
            placa=request.form.get('placa',''),
            vin=request.form.get('vin','').upper(),
            tipo=request.form.get('tipo','sedan'),
            combustible=request.form.get('combustible','gasolina'),
            color=request.form.get('color',''),
            odometro=float(request.form.get('odometro',0) or 0),
            kml_esperado=float(request.form.get('kml_esperado',0) or 0) or None,
            ultimo_servicio_fecha=datetime.strptime(request.form.get('ultimo_servicio_fecha'), '%Y-%m-%d').date() if request.form.get('ultimo_servicio_fecha') else None,
            ultimo_servicio_odo=float(request.form.get('ultimo_servicio_odo',0) or 0) or None,
        )
        db.session.add(v)
        db.session.commit()
        return redirect(url_for('dashboard_usuario'))
    return render_template('vehiculo_form.html', v=None, usuario=u)

@app.route('/usuario/vehiculo/<int:vid>')
@login_requerido
def ver_vehiculo(vid):
    u = usuario_actual()
    v = Vehiculo.query.get_or_404(vid)
    if v.usuario_id != u.id and u.rol != 'admin':
        return redirect(url_for('dashboard_usuario'))
    tareas_con_estado = [{'tarea':t, **calcular_estado_tarea(v,t)} for t in TAREAS]
    servicios = Servicio.query.filter_by(vehiculo_id=vid).order_by(Servicio.fecha.desc()).all()
    combustibles = RegistroCombustible.query.filter_by(vehiculo_id=vid).order_by(RegistroCombustible.fecha.desc()).all()
    lecturas = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.fecha.desc()).limit(10).all()
    documentos = Documento.query.filter_by(vehiculo_id=vid).all()
    docs_con_estado = [{'doc':d,'estado':calcular_estado_documento(d)} for d in documentos]
    return render_template('vehiculo_detalle.html',
        v=v, tareas=tareas_con_estado, servicios=servicios,
        combustibles=combustibles, lecturas=lecturas,
        docs=docs_con_estado, tipos_doc=TIPOS_DOCUMENTO,
        es_admin=(u.rol=='admin'), usuario=u
    )

@app.route('/usuario/vehiculo/<int:vid>/editar', methods=['GET','POST'])
@login_requerido
def editar_vehiculo(vid):
    u = usuario_actual()
    v = Vehiculo.query.get_or_404(vid)
    if v.usuario_id != u.id and u.rol != 'admin':
        return redirect(url_for('dashboard_usuario'))
    if request.method == 'POST':
        v.marca = request.form.get('marca','')
        v.modelo = request.form.get('modelo','')
        v.anio = request.form.get('anio')
        v.placa = request.form.get('placa','')
        v.vin = request.form.get('vin','').upper()
        v.tipo = request.form.get('tipo','sedan')
        v.combustible = request.form.get('combustible','gasolina')
        v.color = request.form.get('color','')
        v.odometro = float(request.form.get('odometro',0) or 0)
        v.kml_esperado = float(request.form.get('kml_esperado',0) or 0) or None
        ls_fecha = request.form.get('ultimo_servicio_fecha')
        v.ultimo_servicio_fecha = datetime.strptime(ls_fecha, '%Y-%m-%d').date() if ls_fecha else None
        ls_odo = request.form.get('ultimo_servicio_odo')
        v.ultimo_servicio_odo = float(ls_odo) if ls_odo else None
        db.session.commit()
        return redirect(url_for('ver_vehiculo', vid=vid))
    return render_template('vehiculo_form.html', v=v, usuario=u)

@app.route('/usuario/vehiculo/<int:vid>/servicio', methods=['POST'])
@login_requerido
def registrar_servicio(vid):
    u = usuario_actual()
    v = Vehiculo.query.get_or_404(vid)
    if v.usuario_id != u.id and u.rol != 'admin':
        return redirect(url_for('dashboard_usuario'))
    tareas = request.form.getlist('tareas')
    fecha_str = request.form.get('fecha')
    odo = float(request.form.get('odometro',0) or 0)
    costo = float(request.form.get('costo',0) or 0) or None
    notas = request.form.get('notas','')
    fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()
    for tid in tareas:
        s = Servicio(vehiculo_id=vid, tarea_id=tid, fecha=fecha, odometro=odo, costo=costo, notas=notas)
        db.session.add(s)
    if odo > v.odometro:
        v.odometro = odo
    lec = LecturaOdo(vehiculo_id=vid, odometro=odo, fecha=fecha, fuente='servicio')
    db.session.add(lec)
    db.session.commit()
    return redirect(url_for('ver_vehiculo', vid=vid))

@app.route('/usuario/vehiculo/<int:vid>/combustible', methods=['POST'])
@login_requerido
def registrar_combustible(vid):
    u = usuario_actual()
    v = Vehiculo.query.get_or_404(vid)
    if v.usuario_id != u.id and u.rol != 'admin':
        return redirect(url_for('dashboard_usuario'))
    fecha_str = request.form.get('fecha')
    odo = float(request.form.get('odometro',0) or 0)
    litros = float(request.form.get('litros',0) or 0)
    costo = float(request.form.get('costo',0) or 0) or None
    precio_litro = round(costo/litros, 3) if costo and litros else None
    lleno = request.form.get('tanque_lleno') == '1'
    notas = request.form.get('notas','')
    fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()
    r = RegistroCombustible(vehiculo_id=vid, fecha=fecha, odometro=odo, litros=litros,
        costo=costo, precio_litro=precio_litro, tanque_lleno=lleno, notas=notas)
    db.session.add(r)
    if odo > v.odometro:
        v.odometro = odo
    lec = LecturaOdo(vehiculo_id=vid, odometro=odo, fecha=fecha, fuente='combustible')
    db.session.add(lec)
    db.session.commit()
    return redirect(url_for('ver_vehiculo', vid=vid))

@app.route('/usuario/vehiculo/<int:vid>/odometro', methods=['POST'])
@login_requerido
def actualizar_odometro(vid):
    u = usuario_actual()
    v = Vehiculo.query.get_or_404(vid)
    if v.usuario_id != u.id and u.rol != 'admin':
        return redirect(url_for('dashboard_usuario'))
    odo = float(request.form.get('odometro',0) or 0)
    if odo > 0:
        if odo > v.odometro:
            v.odometro = odo
        lec = LecturaOdo(vehiculo_id=vid, odometro=odo, fecha=date.today(), fuente='manual')
        db.session.add(lec)
        db.session.commit()
    return redirect(url_for('ver_vehiculo', vid=vid))

# ─── INIT ──────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    if not Usuario.query.filter_by(rol='admin').first():
        admin = Usuario(
            nombre='Administrador',
            email='admin@fleetcare.app',
            password_hash=generate_password_hash('admin2026'),
            rol='admin'
        )
        db.session.add(admin)
        db.session.commit()
        print('Admin creado: admin@fleetcare.app / admin2026')

if __name__ == '__main__':
    app.run(debug=True, port=5001)
