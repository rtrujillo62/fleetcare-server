from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fleetcare-secret-2026')
_data_dir = '/data'
try:
    os.makedirs(_data_dir, exist_ok=True)
    _db_path = f'sqlite:///{_data_dir}/fleetcare.db'
except (OSError, PermissionError):
    _db_path = 'sqlite:///fleetcare.db'

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', _db_path)
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
    capacidad_tanque = db.Column(db.Float)  # litros
    alerta_km = db.Column(db.Float, default=250)  # km antes de vencer para alertar
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
    alerta_km = vehiculo.alerta_km or 250

    ultimo_svc = Servicio.query.filter_by(
        vehiculo_id=vehiculo.id, tarea_id=tarea['id']
    ).order_by(Servicio.fecha.desc()).first()

    ultimo_km = ultimo_svc.odometro if ultimo_svc else (vehiculo.ultimo_servicio_odo or 0)
    ultima_fecha = ultimo_svc.fecha if ultimo_svc else (vehiculo.ultimo_servicio_fecha or date.today())

    meses_diff = (date.today() - ultima_fecha).days / 30.44
    km_diff = vehiculo.odometro - ultimo_km

    proximo_km = ultimo_km + km_intervalo if km_intervalo > 0 else None
    km_restantes = (proximo_km - vehiculo.odometro) if proximo_km else None

    # Estado por km
    if proximo_km and vehiculo.odometro >= proximo_km:
        estado_km = 'red'
    elif km_restantes is not None and km_restantes <= alerta_km:
        estado_km = 'yellow'
    else:
        estado_km = 'green'

    # Estado por tiempo
    if mo_intervalo > 0:
        if meses_diff >= mo_intervalo:
            estado_mo = 'red'
        elif meses_diff >= (mo_intervalo - 1):  # 1 mes antes
            estado_mo = 'yellow'
        else:
            estado_mo = 'green'
    else:
        estado_mo = 'green'

    # El peor de los dos gana
    if 'red' in [estado_km, estado_mo]:
        estado = 'red'
    elif 'yellow' in [estado_km, estado_mo]:
        estado = 'yellow'
    else:
        estado = 'green'

    pct = min(km_diff / km_intervalo if km_intervalo > 0 else 0, 1.0)
    return {'estado': estado, 'pct': pct, 'proximo_km': proximo_km, 'km_restantes': km_restantes}

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

@app.route('/register', methods=['GET','POST'])
def register():
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        nombre = request.form.get('nombre','').strip()
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        password2 = request.form.get('password2','')
        if not nombre or not email or not password:
            error = 'Completa todos los campos'
        elif len(password) < 6:
            error = 'La contraseña debe tener al menos 6 caracteres'
        elif password != password2:
            error = 'Las contraseñas no coinciden'
        elif Usuario.query.filter_by(email=email).first():
            error = 'Ya existe una cuenta con ese correo'
        else:
            u = Usuario(
                nombre=nombre, email=email,
                password_hash=generate_password_hash(password),
                rol='usuario'
            )
            db.session.add(u)
            db.session.commit()
            session['usuario_id'] = u.id
            session['nombre'] = u.nombre
            session['rol'] = u.rol
            return redirect(url_for('dashboard_usuario'))
    return render_template('register.html', error=error)

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
    tareas_con_estado = sorted(
        [{'tarea':t, **calcular_estado_tarea(v,t)} for t in TAREAS],
        key=lambda x: (x['proximo_km'] or 999999)
    )
    servicios = Servicio.query.filter_by(vehiculo_id=vid).order_by(Servicio.fecha.desc()).all()
    combustibles = RegistroCombustible.query.filter_by(vehiculo_id=vid).order_by(RegistroCombustible.fecha.desc()).all()
    lecturas = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.fecha.desc()).limit(10).all()
    documentos = Documento.query.filter_by(vehiculo_id=vid).all()
    docs_con_estado = [{'doc':d,'estado':calcular_estado_documento(d)} for d in documentos]
    error = request.args.get('error')
    return render_template('vehiculo_detalle.html',
        v=v, tareas=tareas_con_estado, servicios=servicios,
        combustibles=combustibles, lecturas=lecturas,
        docs=docs_con_estado, tipos_doc=TIPOS_DOCUMENTO,
        es_admin=True, usuario=usuario_actual(), error=error
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

@app.route('/admin/vehiculo/<int:vid>/intervalos')
@admin_requerido
def editar_intervalos(vid):
    v = Vehiculo.query.get_or_404(vid)
    intervalos = json.loads(v.intervalos or '{}')
    tareas_actuales = []
    for t in TAREAS:
        km_actual = intervalos.get(t['id']+'_km', '')
        mo_actual = intervalos.get(t['id']+'_mo', '')
        tareas_actuales.append({**t, 'km_actual': km_actual, 'mo_actual': mo_actual})
    return render_template('intervalos_form.html', v=v, tareas=tareas_actuales, usuario=usuario_actual())

@app.route('/admin/vehiculo/<int:vid>/intervalos', methods=['POST'])
@admin_requerido
def guardar_intervalos(vid):
    v = Vehiculo.query.get_or_404(vid)
    intervalos = {}
    for t in TAREAS:
        km = request.form.get('km_'+t['id'], '').strip()
        mo = request.form.get('mo_'+t['id'], '').strip()
        if km != '':
            intervalos[t['id']+'_km'] = float(km)
        if mo != '':
            intervalos[t['id']+'_mo'] = float(mo)
    v.intervalos = json.dumps(intervalos)
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
            capacidad_tanque=float(request.form.get('capacidad_tanque',0) or 0) or None,
            alerta_km=float(request.form.get('alerta_km',250) or 250),
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
    tareas_con_estado = sorted(
        [{'tarea':t, **calcular_estado_tarea(v,t)} for t in TAREAS],
        key=lambda x: (x['proximo_km'] or 999999)
    )
    servicios = Servicio.query.filter_by(vehiculo_id=vid).order_by(Servicio.fecha.desc()).all()
    combustibles = RegistroCombustible.query.filter_by(vehiculo_id=vid).order_by(RegistroCombustible.fecha.desc()).all()
    lecturas = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.fecha.desc()).limit(10).all()
    documentos = Documento.query.filter_by(vehiculo_id=vid).all()
    docs_con_estado = [{'doc':d,'estado':calcular_estado_documento(d)} for d in documentos]
    error = request.args.get('error')
    return render_template('vehiculo_detalle.html',
        v=v, tareas=tareas_con_estado, servicios=servicios,
        combustibles=combustibles, lecturas=lecturas,
        docs=docs_con_estado, tipos_doc=TIPOS_DOCUMENTO,
        es_admin=(u.rol=='admin'), usuario=u, error=error
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
        v.capacidad_tanque = float(request.form.get('capacidad_tanque',0) or 0) or None
        v.alerta_km = float(request.form.get('alerta_km',250) or 250)
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

    # Validar odómetro
    ultima_lectura = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.odometro.desc()).first()
    odo_max = ultima_lectura.odometro if ultima_lectura else v.odometro
    if odo < odo_max:
        error = f'El odómetro ingresado ({int(odo):,} km) es menor al último registrado ({int(odo_max):,} km). Por favor verifique.'
        return redirect(url_for('ver_vehiculo', vid=vid, error=error))

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

    # Validar odómetro — no menor al último
    ultima_lectura = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.odometro.desc()).first()
    odo_max = ultima_lectura.odometro if ultima_lectura else v.odometro
    if odo < odo_max:
        error = f'El odómetro ingresado ({int(odo):,} km) es menor al último registrado ({int(odo_max):,} km). Por favor verifique.'
        return redirect(url_for('ver_vehiculo', vid=vid, error=error))

    # Validar odómetro — no mayor al máximo posible (última lectura + kml * capacidad tanque)
    if v.kml_esperado and v.capacidad_tanque:
        max_posible = odo_max + (v.kml_esperado * v.capacidad_tanque)
        if odo > max_posible:
            error = f'El odómetro ingresado ({int(odo):,} km) parece incorrecto. El máximo posible desde la última lectura es {int(max_posible):,} km. Por favor verifique.'
            return redirect(url_for('ver_vehiculo', vid=vid, error=error))

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
        ultima_lectura = LecturaOdo.query.filter_by(vehiculo_id=vid).order_by(LecturaOdo.odometro.desc()).first()
        odo_max = ultima_lectura.odometro if ultima_lectura else v.odometro
        if odo < odo_max:
            return redirect(url_for('ver_vehiculo', vid=vid,
                error=f'El odómetro ingresado ({int(odo):,} km) es menor al último registrado ({int(odo_max):,} km).'))
        if odo > v.odometro:
            v.odometro = odo
        lec = LecturaOdo(vehiculo_id=vid, odometro=odo, fecha=date.today(), fuente='manual')
        db.session.add(lec)
        db.session.commit()
    return redirect(url_for('ver_vehiculo', vid=vid))

# ─── CORREOS ───────────────────────────────────────────────

def enviar_correo(destinatario_email, destinatario_nombre, asunto, cuerpo_html):
    """Envía correo via SendGrid si está configurado, sino solo loguea."""
    sg_key = os.environ.get('SENDGRID_API_KEY')
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@fleetcare.app')
    if not sg_key:
        print(f'[CORREO no configurado] Para: {destinatario_email} | Asunto: {asunto}')
        return False
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg = sendgrid.SendGridAPIClient(api_key=sg_key)
        message = Mail(
            from_email=admin_email,
            to_emails=destinatario_email,
            subject=asunto,
            html_content=cuerpo_html
        )
        sg.send(message)
        return True
    except Exception as e:
        print(f'Error enviando correo: {e}')
        return False

def verificar_y_enviar_alertas():
    """Revisa todos los vehículos y envía correos si hay alertas nuevas."""
    admin = Usuario.query.filter_by(rol='admin').first()
    admin_email = admin.email if admin else os.environ.get('ADMIN_EMAIL','admin@fleetcare.app')

    for v in Vehiculo.query.all():
        usuario = v.propietario
        alertas_red = []
        alertas_yellow = []

        # Revisar tareas de mantenimiento
        for t in TAREAS:
            est = calcular_estado_tarea(v, t)
            if est['estado'] == 'red':
                alertas_red.append(f"🔴 {t['nombre']} — VENCIDO")
            elif est['estado'] == 'yellow':
                km_rest = est.get('km_restantes')
                msg = f"🟡 {t['nombre']}"
                if km_rest: msg += f" — faltan {int(km_rest):,} km"
                alertas_yellow.append(msg)

        # Revisar documentos
        for doc in v.documentos:
            est = calcular_estado_documento(doc)
            if doc.vencimiento:
                dias = (doc.vencimiento - date.today()).days
                if est == 'red':
                    alertas_red.append(f"🔴 {doc.tipo.capitalize()} — VENCIDO")
                elif est == 'yellow':
                    alertas_yellow.append(f"🟡 {doc.tipo.capitalize()} — vence en {dias} días")

        if not alertas_red and not alertas_yellow:
            continue

        # Armar y enviar correo
        nombre_vehiculo = f"{v.marca} {v.modelo} {v.anio} ({v.placa})"
        todas_alertas = alertas_red + alertas_yellow
        lista_html = ''.join(f'<li style="margin-bottom:6px">{a}</li>' for a in todas_alertas)

        cuerpo = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto">
          <h2 style="color:#1D9E75">⚙ FleetCare — Alerta de mantenimiento</h2>
          <p>Hola <strong>{usuario.nombre}</strong>,</p>
          <p>Su vehículo <strong>{nombre_vehiculo}</strong> requiere atención:</p>
          <ul style="background:#f9f9f9;padding:16px 24px;border-radius:8px;border:1px solid #eee">
            {lista_html}
          </ul>
          <p>Por favor contacte a su Fleet Manager para coordinar el servicio.</p>
          <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
          <p style="font-size:12px;color:#999">FleetCare — Sistema de mantenimiento preventivo</p>
        </div>"""

        asunto = f'FleetCare: {len(alertas_red)} vencido(s), {len(alertas_yellow)} próximo(s) — {v.marca} {v.modelo}'
        enviar_correo(usuario.email, usuario.nombre, asunto, cuerpo)
        if admin and admin.email != usuario.email:
            enviar_correo(admin.email, 'Administrador', f'[Admin] {asunto}', cuerpo)

@app.route('/admin/enviar-alertas')
@admin_requerido
def enviar_alertas_manual():
    """El admin puede disparar el envío de alertas manualmente."""
    with app.app_context():
        verificar_y_enviar_alertas()
    return redirect(url_for('dashboard_admin'))

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
