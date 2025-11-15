from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import csv
import io
from functools import wraps 
from operator import itemgetter 
import datetime
from datetime import timedelta
from dateutil import parser 

# --- CONFIGURACIÓN INICIAL ---
app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui_para_seguridad' 

# Lista de meses para ordenar
MESES_ORDEN = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# --- FUNCIONES AUXILIARES DE BASE DE DATOS ---

def get_conn():
    c = sqlite3.connect('demo.db') 
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with get_conn() as c:
        # TABLA SUSCEPTIBLE
        c.execute('''
            CREATE TABLE IF NOT EXISTS susceptible (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_nino TEXT,
                fecha_nacimiento TEXT, 
                nombre_madre TEXT, 
                comunidad TEXT,
                vacuna_pendiente TEXT,
                anio TEXT NOT NULL,
                mes TEXT NOT NULL,
                es_eliminado INTEGER DEFAULT 0,
                fecha_eliminacion TEXT NULL
            )
        ''')
        
        # TABLA METADATOS
        c.execute('''
            CREATE TABLE IF NOT EXISTS metadatos_tablas (
                anio TEXT NOT NULL,
                mes TEXT NOT NULL,
                responsable TEXT DEFAULT 'PENDIENTE',
                municipio TEXT DEFAULT 'PENDIENTE',
                puesto_salud TEXT DEFAULT 'PENDIENTE',
                es_eliminado INTEGER DEFAULT 0,
                fecha_eliminacion TEXT NULL,
                PRIMARY KEY (anio, mes)
            )
        ''')
        
        # Lógica de ALTER TABLE para asegurar que las columnas de Soft Delete existan
        try:
            c.execute("ALTER TABLE susceptible ADD COLUMN es_eliminado INTEGER DEFAULT 0")
            c.execute("ALTER TABLE susceptible ADD COLUMN fecha_eliminacion TEXT NULL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE metadatos_tablas ADD COLUMN es_eliminado INTEGER DEFAULT 0")
            c.execute("ALTER TABLE metadatos_tablas ADD COLUMN fecha_eliminacion TEXT NULL")
        except sqlite3.OperationalError:
            pass
        
init_db()

# --- DECORADOR Y AUXILIARES ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_current_period():
    """Extrae anio y mes de las variables de sesión."""
    anio = session.get('tabla_actual')
    mes = session.get('mes_activo') 
    return anio, mes

# ⭐️ FUNCIÓN DE LIMPIEZA PERIÓDICA (Eliminación Definitiva) ⭐️
def limpiar_papelera_definitiva():
    """Elimina permanentemente los registros de la papelera con más de 30 días."""
    
    fecha_limite = (datetime.datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')

    with get_conn() as c:
        # 1. Eliminar Susceptibles individuales
        c.execute('DELETE FROM susceptible WHERE es_eliminado = 1 AND fecha_eliminacion < ?', (fecha_limite,))
        
        # 2. Eliminar Metadatos (Meses/Años)
        c.execute('DELETE FROM metadatos_tablas WHERE es_eliminado = 1 AND fecha_eliminacion < ?', (fecha_limite,))
        
        c.commit()

@app.before_request
def cleanup_papelera():
    limpiar_papelera_definitiva()


# --- RUTAS DE AUTENTICACIÓN Y SELECCIÓN ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contrasena = request.form['contrasena']
        
        if usuario == 'idanea' and contrasena == 'IDANEA37quej':
            session['logged_in'] = True
            session['username'] = 'admin'
            return redirect(url_for('seleccion_anio')) 
        else:
            flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('tabla_actual', None) 
    session.pop('mes_activo', None)
    flash('Sesión cerrada', 'info')
    return redirect(url_for('login'))

@app.route('/seleccion', methods=['GET', 'POST'])
@login_required 
def seleccion_anio():
    with get_conn() as c:
        # FILTRO: Solo años activos (es_eliminado = 0)
        tablas = c.execute('SELECT anio, responsable, municipio FROM metadatos_tablas WHERE mes="Enero" AND es_eliminado = 0 ORDER BY anio DESC').fetchall()
    
    if request.method == 'POST':
        anio_seleccionado = request.form['anio_seleccionado']
        
        with get_conn() as c:
            cursor = c.cursor()
            meses_existentes = cursor.execute('SELECT mes FROM metadatos_tablas WHERE anio=? AND mes="Enero" AND es_eliminado = 0', (anio_seleccionado,)).fetchone()
            
            if not meses_existentes:
                try:
                    for mes_nombre in MESES_ORDEN:
                        cursor.execute('INSERT INTO metadatos_tablas (anio, mes) VALUES (?, ?)', (anio_seleccionado, mes_nombre))
                    c.commit()
                    flash(f'Año {anio_seleccionado} creado. Los 12 meses están listos para trabajar.', 'info')
                except sqlite3.IntegrityError:
                    pass
                except Exception as e:
                    c.rollback()
                    flash(f'Error al generar meses: {e}', 'danger')
        
        session['tabla_actual'] = anio_seleccionado 
        session.pop('mes_activo', None) 
            
        return redirect(url_for('gestion_mes', anio=anio_seleccionado))

    return render_template('seleccion.html', tablas=tablas)

# --- RUTA DE ELIMINACIÓN COMPLETA DEL AÑO (Soft Delete) ---
@app.route('/eliminar_anio_completo/<string:anio>', methods=['POST'])
@login_required 
def eliminar_anio_completo(anio):
    current_anio = session.get('tabla_actual')
    
    if anio == current_anio:
        flash(f'No puedes eliminar el año {anio} mientras está seleccionado como activo. Selecciona otro año primero.', 'danger')
        return redirect(url_for('seleccion_anio'))

    fecha_actual = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_conn() as c:
        cursor = c.cursor()
        try:
            # SOFT DELETE 1: Marcar TODOS los susceptibles de ese AÑO como eliminados
            cursor.execute('UPDATE susceptible SET es_eliminado = 1, fecha_eliminacion = ? WHERE anio=?', (fecha_actual, anio))
            registros_susceptibles = cursor.rowcount
            
            # SOFT DELETE 2: Marcar TODOS los metadatos (todos los meses) de ese AÑO como eliminados
            cursor.execute('UPDATE metadatos_tablas SET es_eliminado = 1, fecha_eliminacion = ? WHERE anio=?', (fecha_actual, anio))
            registros_metadatos = cursor.rowcount
            
            c.commit()
            
            flash(f'Año {anio} (y sus {registros_susceptibles} susceptibles) enviado a la papelera. Puede recuperarlo en 30 días.', 'warning')
            
        except Exception as e:
            c.rollback()
            flash(f'Error al enviar el año {anio} a la papelera: {e}', 'danger')
            
    return redirect(url_for('seleccion_anio'))

# --- RUTA DE GESTIÓN DE MESES ---

@app.route('/gestion_mes/<string:anio>', methods=['GET', 'POST'])
@login_required
def gestion_mes(anio):
    session['tabla_actual'] = anio
    meses_info = []
    
    with get_conn() as c:
        # FILTRO: Solo meses activos (es_eliminado = 0)
        meses_data = c.execute('SELECT anio, mes, responsable, municipio, puesto_salud FROM metadatos_tablas WHERE anio=? AND es_eliminado = 0 ORDER BY anio, mes', (anio,)).fetchall()
        
        for mes_data in meses_data:
            meses_info.append(mes_data)

    if request.method == 'POST':
        mes_seleccionado = request.form.get('mes_seleccionado')
        mes_a_duplicar = request.form.get('mes_a_duplicar')
        
        if mes_seleccionado:
            session['mes_activo'] = mes_seleccionado
            flash(f'Período activo: {mes_seleccionado} {anio}', 'info')
            return redirect(url_for('home'))
        
        elif mes_a_duplicar:
            base_mes = mes_a_duplicar.split(' (')[0]
            
            with get_conn() as c:
                cursor = c.cursor()
                
                # FILTRO: Solo buscar duplicados en meses activos
                duplicados_data = cursor.execute('SELECT mes FROM metadatos_tablas WHERE anio=? AND mes LIKE ? AND es_eliminado = 0', (anio, f'{base_mes}%')).fetchall()
                
                max_num = 0
                for row in duplicados_data:
                    mes_nombre = row['mes']
                    if mes_nombre.endswith(')'):
                        try:
                            num = int(mes_nombre.split('(')[-1].replace(')', ''))
                            max_num = max(max_num, num)
                        except ValueError:
                            pass
                    elif mes_nombre == base_mes and base_mes in MESES_ORDEN:
                        max_num = max(max_num, 1)

                mes_nuevo_duplicado = f"{base_mes} ({max_num + 1})"
                
                # FILTRO: Solo obtener metadatos del mes activo para copiar
                meta_original = cursor.execute('SELECT responsable, municipio, puesto_salud FROM metadatos_tablas WHERE anio=? AND mes=? AND es_eliminado = 0', (anio, mes_a_duplicar)).fetchone()
                
                if meta_original:
                    try:
                        cursor.execute("""
                            INSERT INTO metadatos_tablas (anio, mes, responsable, municipio, puesto_salud) 
                            VALUES (?, ?, ?, ?, ?)
                        """, (anio, mes_nuevo_duplicado, meta_original['responsable'], meta_original['municipio'], meta_original['puesto_salud']))
                        c.commit()
                        
                        session['mes_activo'] = mes_nuevo_duplicado
                        flash(f'Período {mes_nuevo_duplicado} {anio} creado y seleccionado con metadatos duplicados.', 'success')
                        return redirect(url_for('home'))
                        
                    except sqlite3.IntegrityError:
                        flash(f'Error de duplicado. El nombre "{mes_nuevo_duplicado}" ya está en uso. Intenta de nuevo.', 'danger')
                        return redirect(url_for('gestion_mes', anio=anio))
                    
                else:
                    flash('Error al encontrar metadatos del mes original.', 'danger')

    meses_info_ordenada = sorted(meses_info, key=lambda d: (MESES_ORDEN.index(d['mes'].split(' (')[0]) if d['mes'].split(' (')[0] in MESES_ORDEN else 99, d['mes']))

    return render_template('gestion_mes.html', anio=anio, meses_info_ordenada=meses_info_ordenada, MESES_ORDEN=MESES_ORDEN)

# --- RUTA DE ELIMINACIÓN PERMANENTE (Soft Delete de Meses Duplicados) ---

@app.route('/eliminar_periodo/<string:anio>/<string:mes>', methods=['POST'])
@login_required 
def eliminar_periodo(anio, mes):
    current_anio, current_mes = get_current_period()
    
    if anio == current_anio and mes == current_mes:
        flash(f'No puedes eliminar el período {anio}-{mes} mientras está activo. Selecciona otro primero.', 'danger')
        return redirect(url_for('gestion_mes', anio=anio))

    fecha_actual = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_conn() as c:
        cursor = c.cursor()
        try:
            # SOFT DELETE 1: Marcar registros de susceptibles como eliminados
            sql_sus = 'UPDATE susceptible SET es_eliminado = 1, fecha_eliminacion = ? WHERE anio=? AND mes=? AND es_eliminado = 0'
            cursor.execute(sql_sus, (fecha_actual, anio, mes))
            registros_eliminados = cursor.rowcount
            
            # SOFT DELETE 2: Marcar el registro de metadatos como eliminado
            sql_meta = 'UPDATE metadatos_tablas SET es_eliminado = 1, fecha_eliminacion = ? WHERE anio=? AND mes=? AND es_eliminado = 0'
            cursor.execute(sql_meta, (fecha_actual, anio, mes))
            
            c.commit()
            
            flash(f'Período {anio}-{mes} y sus {registros_eliminados} registros han sido enviados a la papelera. Puede recuperarlos en 30 días.', 'warning')
            
        except Exception as e:
            c.rollback()
            flash(f'Error al enviar el período {anio}-{mes} a la papelera: {e}', 'danger')
            
    return redirect(url_for('gestion_mes', anio=anio))

# --- RUTA: VACIAR REGISTROS DE UN MES (Soft Delete de Susceptibles) ---
@app.route('/vaciar_mes/<string:anio>/<string:mes>', methods=['POST'])
@login_required 
def vaciar_mes(anio, mes):
    current_anio, current_mes = get_current_period()

    if anio == current_anio and mes == current_mes:
        flash(f'No puedes vaciar los registros del mes {mes} mientras está activo. Selecciona otro período o usa el botón "Entrar" para ver los datos.', 'danger')
        return redirect(url_for('gestion_mes', anio=anio))
    
    fecha_actual = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with get_conn() as c:
        cursor = c.cursor()
        try:
            # SOFT DELETE: Marcar SOLAMENTE los registros de susceptibles como eliminados
            sql = 'UPDATE susceptible SET es_eliminado = 1, fecha_eliminacion = ? WHERE anio=? AND mes=? AND es_eliminado = 0'
            cursor.execute(sql, (fecha_actual, anio, mes))
            registros_eliminados = cursor.rowcount
            c.commit()
            
            flash(f'Se enviaron {registros_eliminados} registros a la papelera del mes {anio}-{mes}. Los metadatos se mantuvieron.', 'warning')
            
        except Exception as e:
            c.rollback()
            flash(f'Error al enviar los registros del mes {anio}-{mes} a la papelera: {e}', 'danger')
            
    return redirect(url_for('gestion_mes', anio=anio))

# --- RUTA DE EDICIÓN DE METADATOS ---

@app.route('/editar_metadatos', methods=['GET', 'POST'])
@login_required
def editar_metadatos():
    anio_actual, mes_actual = get_current_period()
    if not anio_actual or not mes_actual: 
        return redirect(url_for('seleccion_anio'))

    with get_conn() as c:
        metadatos = c.execute('SELECT * FROM metadatos_tablas WHERE anio=? AND mes=? AND es_eliminado = 0', (anio_actual, mes_actual)).fetchone()
    
    if request.method == 'POST':
        responsable = request.form['responsable']
        municipio = request.form['municipio']
        puesto_salud = request.form['puesto_salud']

        with get_conn() as c:
            sql = 'UPDATE metadatos_tablas SET responsable=?, municipio=?, puesto_salud=? WHERE anio=? AND mes=? AND es_eliminado = 0'
            c.execute(sql, (responsable, municipio, puesto_salud, anio_actual, mes_actual))
        
        flash(f'Metadatos para el período {anio_actual}-{mes_actual} actualizados', 'info')
        return redirect(url_for('home'))
        
    return render_template('editar_metadatos.html', metadatos=metadatos, anio=anio_actual, mes=mes_actual)


# --- RUTA PRINCIPAL DE LISTADO (home) ---

@app.route('/')
@login_required 
def home():
    anio_actual, mes_actual = get_current_period()
    
    if not anio_actual: 
        return redirect(url_for('seleccion_anio'))
    
    if anio_actual and not mes_actual:
        flash('Selecciona un mes para trabajar.', 'warning')
        return redirect(url_for('gestion_mes', anio=anio_actual))
    
    busqueda = request.args.get('q') 
    
    with get_conn() as c:
        metadatos = c.execute('SELECT * FROM metadatos_tablas WHERE anio=? AND mes=? AND es_eliminado = 0', (anio_actual, mes_actual)).fetchone()
        
        meses_data = c.execute('SELECT mes FROM metadatos_tablas WHERE anio=? AND es_eliminado = 0 GROUP BY mes', (anio_actual,)).fetchall()
        meses_disponibles = sorted([d['mes'] for d in meses_data], key=lambda m: MESES_ORDEN.index(m.split(' (')[0]) if m.split(' (')[0] in MESES_ORDEN else 99)

        if busqueda:
            query = """
                SELECT id, nombre_nino, fecha_nacimiento, nombre_madre, comunidad, vacuna_pendiente 
                FROM susceptible 
                WHERE anio=? AND mes=? AND es_eliminado = 0 AND (nombre_nino LIKE ? OR comunidad LIKE ?)
                ORDER BY id DESC
            """
            param = (anio_actual, mes_actual, '%' + busqueda + '%', '%' + busqueda + '%')
            data = c.execute(query, param).fetchall()
        else:
            query = 'SELECT id,nombre_nino,fecha_nacimiento,nombre_madre,comunidad,vacuna_pendiente FROM susceptible WHERE anio=? AND mes=? AND es_eliminado = 0 ORDER BY id DESC'
            data = c.execute(query, (anio_actual, mes_actual)).fetchall()

        total_registros = c.execute('SELECT COUNT(id) FROM susceptible WHERE anio=? AND mes=? AND es_eliminado = 0', (anio_actual, mes_actual)).fetchone()[0]
        
        total_pendientes = c.execute("""
            SELECT COUNT(id) 
            FROM susceptible 
            WHERE anio=? AND mes=? AND es_eliminado = 0
              AND vacuna_pendiente IS NOT NULL 
              AND vacuna_pendiente != '' 
              AND vacuna_pendiente != 'NINGUNA' 
        """, (anio_actual, mes_actual)).fetchone()[0]
            
    return render_template('index.html', 
        est=data, 
        metadatos=metadatos, 
        anio=anio_actual, 
        mes=mes_actual,
        meses_disponibles=meses_disponibles,
        total_registros=total_registros, 
        total_pendientes=total_pendientes 
    )

# --- RUTAS CRUD SECUNDARIAS (Se mantienen) ---
@app.route('/crear', methods=['POST', 'GET'])
@login_required
def crear():
    anio_actual, mes_actual = get_current_period()
    if not anio_actual or not mes_actual: 
        flash('Selecciona un período de trabajo (año y mes) antes de crear registros.', 'danger')
        return redirect(url_for('seleccion_anio'))
    
    if request.method == 'POST':
        nn = request.form['nombre_nino']
        fn = request.form['fecha_nacimiento']
        nm = request.form['nombre_madre']
        com = request.form['comunidad']
        vp = request.form['vacuna_pendiente']
        
        with get_conn() as c:
            sql = 'INSERT INTO susceptible(nombre_nino,fecha_nacimiento,nombre_madre,comunidad,vacuna_pendiente, anio, mes, es_eliminado) VALUES(?,?,?,?,?,?,?, 0)'
            c.execute(sql, (nn, fn, nm, com, vp, anio_actual, mes_actual))
            
        flash('Susceptible registrado','success')
        return redirect(url_for('home'))
        
    return render_template('crear.html')

@app.route('/detalles/<int:id>')
@login_required
def detalles(id):
    anio_actual, mes_actual = get_current_period()
    if not anio_actual or not mes_actual: return redirect(url_for('seleccion_anio'))
    
    with get_conn() as c:
        sql = 'SELECT id,nombre_nino,fecha_nacimiento,nombre_madre,comunidad,vacuna_pendiente FROM susceptible WHERE id=? AND anio=? AND mes=? AND es_eliminado = 0'
        est = c.execute(sql,(id, anio_actual, mes_actual)).fetchone()
    
    if est is None:
        flash('Registro no encontrado o no pertenece al período actual', 'danger')
        return redirect(url_for('home'))
    return render_template('detalles.html', est=est)

@app.route('/editar/<int:id>', methods=['POST', 'GET'])
@login_required
def editar(id):
    anio_actual, mes_actual = get_current_period()
    if not anio_actual or not mes_actual: return redirect(url_for('seleccion_anio'))
    
    with get_conn() as c:
        sql = 'SELECT id,nombre_nino,fecha_nacimiento,nombre_madre,comunidad,vacuna_pendiente FROM susceptible WHERE id=? AND anio=? AND mes=? AND es_eliminado = 0'
        est = c.execute(sql,(id, anio_actual, mes_actual)).fetchone()
        
    if est is None:
        flash('Registro no encontrado', 'danger')
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        nn = request.form['nombre_nino']
        fn = request.form['fecha_nacimiento']
        nm = request.form['nombre_madre']
        com = request.form['comunidad']
        vp = request.form['vacuna_pendiente']
        
        with get_conn() as c:
            sql = 'UPDATE susceptible SET nombre_nino=?, fecha_nacimiento=?, nombre_madre=?, comunidad=?, vacuna_pendiente=? WHERE id=? AND anio=? AND mes=? AND es_eliminado = 0'
            c.execute(sql, (nn, fn, nm, com, vp, id, anio_actual, mes_actual))
        
        flash('Registro actualizado','info') 
        return redirect(url_for('home'))
        
    return render_template('editar.html', est=est)

@app.route('/eliminar/<int:id>', methods=['POST', 'GET'])
@login_required
def eliminar(id):
    anio_actual, mes_actual = get_current_period()
    if not anio_actual or not mes_actual: return redirect(url_for('seleccion_anio'))
    
    if request.method == 'POST':
        fecha_actual = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with get_conn() as c:
            sql = 'UPDATE susceptible SET es_eliminado = 1, fecha_eliminacion = ? WHERE id=? AND anio=? AND mes=? AND es_eliminado = 0'
            c.execute(sql, (fecha_actual, id, anio_actual, mes_actual))
        flash('Registro enviado a la papelera. Puede recuperarlo en 30 días.', 'warning') 
        return redirect(url_for('home'))
        
    with get_conn() as c:
        sql = 'SELECT id,nombre_nino,nombre_madre FROM susceptible WHERE id=? AND anio=? AND mes=? AND es_eliminado = 0'
        est = c.execute(sql,(id, anio_actual, mes_actual)).fetchone()
    
    if est is None:
        flash('Registro no encontrado', 'danger')
        return redirect(url_for('home'))
        
    return render_template('eliminar.html', est=est)

# --- RUTA DE LA PAPELERA (CON AGRUPACIÓN JERÁRQUICA) ---

@app.route('/papelera')
@login_required
def papelera():
    with get_conn() as c:
        # 1. Obtener todos los elementos de metadatos eliminados (años y meses)
        elementos_meta = c.execute("""
            SELECT anio, mes, fecha_eliminacion, responsable, 'periodo' as tipo 
            FROM metadatos_tablas 
            WHERE es_eliminado = 1 
            ORDER BY fecha_eliminacion DESC
        """).fetchall()

        # 2. Obtener todos los susceptibles eliminados
        elementos_susceptible = c.execute("""
            SELECT id, nombre_nino, anio, mes, fecha_eliminacion, 'susceptible' as tipo 
            FROM susceptible 
            WHERE es_eliminado = 1 
            ORDER BY fecha_eliminacion DESC
        """).fetchall()

    # 3. Procesamiento y Creación de Jerarquía
    papelera_jerarquica = {}
    fecha_actual_str = datetime.datetime.now().strftime('%Y-%m-%d')

    # Procesar Metadatos (Estructura base Año y Mes)
    for elem in elementos_meta:
        anio = elem['anio']
        mes = elem['mes']
        
        # Inicializar la estructura del año si no existe
        if anio not in papelera_jerarquica:
            papelera_jerarquica[anio] = {'Meses': {}, 'Total_Eliminados': 0}

        # Inicializar el mes si no existe
        if mes not in papelera_jerarquica[anio]['Meses']:
            papelera_jerarquica[anio]['Meses'][mes] = {'Registros': []}

        # Almacenar el metadato del mes (para recuperación masiva del mes)
        papelera_jerarquica[anio]['Meses'][mes]['Metadato'] = {
            'id_clave': anio + mes,
            'nombre': f"{mes} ({anio})",
            'tipo': 'periodo',
            'fecha_eliminacion': elem['fecha_eliminacion'],
            'fecha_caducidad': (parser.parse(elem['fecha_eliminacion']) + timedelta(days=30)).strftime('%Y-%m-%d')
        }
        papelera_jerarquica[anio]['Total_Eliminados'] += 1
        
    # Procesar Registros Susceptibles (Dentro de la estructura Mes)
    for elem in elementos_susceptible:
        anio = elem['anio']
        mes = elem['mes']
        
        # Asegurarse de que el año y mes existan en la estructura
        if anio not in papelera_jerarquica:
             papelera_jerarquica[anio] = {'Meses': {}, 'Total_Eliminados': 0}
        if mes not in papelera_jerarquica[anio]['Meses']:
             papelera_jerarquica[anio]['Meses'][mes] = {'Registros': []} # Registros sin metadatos de mes (solo si se usó /vaciar_mes)

        # Almacenar el registro susceptible
        papelera_jerarquica[anio]['Meses'][mes]['Registros'].append({
            'id_clave': str(elem['id']),
            'nombre': elem['nombre_nino'],
            'tipo': 'susceptible',
            'fecha_eliminacion': elem['fecha_eliminacion'],
            'fecha_caducidad': (parser.parse(elem['fecha_eliminacion']) + timedelta(days=30)).strftime('%Y-%m-%d')
        })
        papelera_jerarquica[anio]['Total_Eliminados'] += 1
        
    # Ordenar los meses dentro de cada año
    for anio in papelera_jerarquica:
        meses_ordenados = sorted(papelera_jerarquica[anio]['Meses'].items(), 
                                key=lambda item: (MESES_ORDEN.index(item[0].split(' (')[0]) if item[0].split(' (')[0] in MESES_ORDEN else 99, item[0]))
        papelera_jerarquica[anio]['Meses'] = dict(meses_ordenados)

    return render_template('papelera.html', papelera_jerarquica=papelera_jerarquica, fecha_actual_str=fecha_actual_str)

# --- RUTA DE RECUPERACIÓN (MASIVA E INDIVIDUAL) ---

@app.route('/recuperar/<string:tipo>/<path:clave>', methods=['POST'])
@login_required
def recuperar(tipo, clave):
    with get_conn() as c:
        if tipo == 'susceptible':
            # CLAVE es el ID del susceptible
            sql = 'UPDATE susceptible SET es_eliminado = 0, fecha_eliminacion = NULL WHERE id=?'
            c.execute(sql, (clave,))
            flash('Registro individual recuperado con éxito.', 'success')
            
        elif tipo == 'periodo':
            # CLAVE es ANIO + MES
            if len(clave) >= 4: 
                anio = clave[:4]
                mes = clave[4:]
                
                # Recuperar Metadato del mes
                sql_meta = 'UPDATE metadatos_tablas SET es_eliminado = 0, fecha_eliminacion = NULL WHERE anio=? AND mes=?'
                c.execute(sql_meta, (anio, mes))
                
                # Recuperar todos los Susceptibles de ese mes
                sql_sus = 'UPDATE susceptible SET es_eliminado = 0, fecha_eliminacion = NULL WHERE anio=? AND mes=?'
                c.execute(sql_sus, (anio, mes))
                
                flash(f'Período completo {mes} {anio} y sus registros han sido recuperados con éxito.', 'success')

        elif tipo == 'anio':
            # CLAVE es solo el ANIO
            anio = clave
            
            # Recuperar todos los metadatos (meses) de ese año
            sql_meta = 'UPDATE metadatos_tablas SET es_eliminado = 0, fecha_eliminacion = NULL WHERE anio=?'
            c.execute(sql_meta, (anio,))
            
            # Recuperar todos los susceptibles de ese año
            sql_sus = 'UPDATE susceptible SET es_eliminado = 0, fecha_eliminacion = NULL WHERE anio=?'
            c.execute(sql_sus, (anio,))
            
            flash(f'Año completo {anio} y todos sus contenidos han sido recuperados.', 'success')

        else:
            flash('Error al recuperar el elemento: tipo desconocido.', 'danger')
            return redirect(url_for('papelera'))
            
        c.commit()
        
    return redirect(url_for('papelera'))


# --- EJECUCIÓN ---
if __name__ == '__main__':
    app.run(debug=True)