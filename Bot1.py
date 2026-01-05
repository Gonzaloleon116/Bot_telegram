import os
import threading
import re
import datetime
import pytz
from http.server import SimpleHTTPRequestHandler, HTTPServer
import mysql.connector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from telegram.request import HTTPXRequest

# --- CONFIGURACIÓN ---
# Cambia esto si tus usuarios están en otro país
ZONA_HORARIA = 'America/Mexico_City'

# --- 1. SERVIDOR FALSO (Para mantener vivo a Render) ---
def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🖥️ Servidor falso corriendo en el puerto {port}")
    server.serve_forever()

# --- 2. CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=os.getenv("MYSQLPORT")
    )

# --- 3. LÓGICA DE ALARMA DIARIA (PLAN DE LECTURA) ---
async def enviar_recordatorio(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    telegram_id = job.chat_id
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # A. Buscamos categoría del usuario
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        res_cat = cursor.fetchone()
        
        if not res_cat:
            conn.close()
            return 
        
        categoria_usuario = res_cat[0]
        
        # B. Obtenemos la FECHA ACTUAL (Mes y Día)
        ahora = datetime.datetime.now(pytz.timezone(ZONA_HORARIA))
        mes_actual = ahora.month
        dia_actual = ahora.day
        
        # C. CONSULTA PROFESIONAL (JOIN)
        # Unimos 'plan_lectura' con 'libros' usando el ID para traer el nombre real
        sql = """
            SELECT 
                libros.nombre,          -- Nombre del libro (Ej: Génesis)
                plan_lectura.capitulos, -- Capítulos (Ej: 1-3)
                plan_lectura.mensaje    -- Comentario del día
            FROM plan_lectura
            INNER JOIN libros ON plan_lectura.libro_id = libros.id
            WHERE 
                plan_lectura.categoria = %s AND 
                plan_lectura.mes = %s AND 
                plan_lectura.dia = %s
            LIMIT 1
        """
        
        cursor.execute(sql, (categoria_usuario, mes_actual, dia_actual))
        resultado = cursor.fetchone()
        conn.close()
        
        if resultado:
            nombre_libro = resultado[0]
            capitulos = resultado[1]
            comentario = resultado[2]
            
            # Mensaje bonito
            msg = (
                f"🔔 **Plan Diario - {dia_actual}/{mes_actual}**\n\n"
                f"📖 **Lectura de hoy:**\n"
                f"👉 *{nombre_libro} {capitulos}*\n\n"
                f"💭 _{comentario}_"
            )
            await context.bot.send_message(chat_id=telegram_id, text=msg, parse_mode="Markdown")
        else:
            # Si no hay lectura cargada para hoy en la base de datos
            await context.bot.send_message(
                chat_id=telegram_id, 
                text=f"📅 Hoy es {dia_actual}/{mes_actual}. ¡Día de descanso o lectura libre! (No hay plan cargado)."
            )
            
    except Exception as e:
        print(f"Error enviando alarma a {telegram_id}: {e}")

# --- 4. FUNCIÓN PARA GUARDAR HORA Y ACTIVAR ALARMA ---
async def guardar_y_activar_alarma(chat_id, hora_str, context):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Guardamos preferencia de hora
        sql = """
            INSERT INTO usuarios (telegram_id, hora_recordatorio, categoria) 
            VALUES (%s, %s, 'joven') 
            ON DUPLICATE KEY UPDATE hora_recordatorio = %s
        """
        cursor.execute(sql, (chat_id, hora_str, hora_str))
        conn.commit()
        conn.close()

        # Limpiamos alarmas viejas para no duplicar
        jobs_existentes = context.job_queue.get_jobs_by_name(str(chat_id))
        for job in jobs_existentes:
            job.schedule_removal()
            
        # Programamos la nueva alarma
        h, m = map(int, hora_str.split(':'))
        time_to_run = datetime.time(hour=h, minute=m, tzinfo=pytz.timezone(ZONA_HORARIA))
        
        context.job_queue.run_daily(enviar_recordatorio, time_to_run, chat_id=chat_id, name=str(chat_id))
        
        return True
    except Exception as e:
        print(f"Error programando: {e}")
        return False

# --- 5. COMANDOS DEL BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Definimos los botones de categoría
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="cat_nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="cat_joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="cat_adulto")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Creamos el mensaje de bienvenida detallado
    mensaje_bienvenida = (
        "👋 **¡Bienvenido a tu Asistente Bíblico!**\n\n"
        "Estoy diseñado para ayudarte a mantener tu hábito de lectura y fortalecer tu fe día a día.\n\n"
        "🛠 **¿Qué puedo hacer por ti?**\n"
        "🔹 `/cita`  → Te envío un versículo aleatorio de ánimo al instante.\n"
        "🔹 `/programar` → Configuro una alarma diaria para enviarte tu plan de lectura.\n"
        "🔹 `/start` → Reiniciamos el bot y cambias tu categoría.\n\n"
        "👇 **Para comenzar, por favor elige tu etapa de vida:**"
    )

    # Enviamos el mensaje
    await update.message.reply_text(
        mensaje_bienvenida, 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )

# COMANDO /cita (Aleatorio - Usa la tabla vieja 'citas')
async def enviar_cita_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificamos categoría
        cursor.execute("SELECT categoria FROM usuarios WHERE telegram_id = %s", (telegram_id,))
        res = cursor.fetchone()
        
        if not res:
            await update.message.reply_text("⚠️ Usa /start primero para registrarte.")
            conn.close()
            return
            
        # Consulta a la tabla de versículos sueltos
        cursor.execute("SELECT frase, referencia FROM citas WHERE categoria = %s ORDER BY RAND() LIMIT 1", (res[0],))
        cita = cursor.fetchone()
        conn.close()
        
        if cita:
            await update.message.reply_text(f"✨ **Versículo Ánimo:**\n\n_{cita[0]}_\n📖 {cita[1]}", parse_mode="Markdown")
        else:
            await update.message.reply_text("No hay versículos aleatorios disponibles aún.")
    except Exception:
        await update.message.reply_text("❌ Error de conexión.")

# COMANDO /programar (Configuración de hora)
async def programar_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Si el usuario escribe: /programar 07:00
    if context.args:
        hora_input = context.args[0]
        chat_id = update.effective_chat.id
        
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", hora_input):
            await update.message.reply_text("❌ Formato incorrecto. Usa HH:MM (ej: 07:00).")
            return

        exito = await guardar_y_activar_alarma(chat_id, hora_input, context)
        if exito:
            await update.message.reply_text(f"✅ ¡Listo! Alarma configurada a las **{hora_input}**.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Error guardando la hora.")
        return

    # Si solo escribe /programar, mostramos botones
    keyboard = [
        [InlineKeyboardButton("🌅 06:00 AM", callback_data="time_06:00"), InlineKeyboardButton("☀️ 07:00 AM", callback_data="time_07:00")],
        [InlineKeyboardButton("🕗 08:00 AM", callback_data="time_08:00"), InlineKeyboardButton("🌙 09:00 PM", callback_data="time_21:00")],
        [InlineKeyboardButton("✏️ Escribir otra", callback_data="time_manual")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⏰ **Configura tu Recordatorio**\n\n"
        "Elige una hora rápida o escribe la tuya propia:", 
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# MANEJADOR DE BOTONES (Categorías y Horas)
async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.from_user.id

    # Caso 1: Eligió Categoría
    if data.startswith("cat_"):
        categoria = data.replace("cat_", "")
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            sql = "INSERT INTO usuarios (telegram_id, categoria) VALUES (%s, %s) ON DUPLICATE KEY UPDATE categoria = %s"
            cursor.execute(sql, (chat_id, categoria, categoria))
            conn.commit()
            conn.close()
            
            await query.edit_message_text(
                f"✅ Categoría guardada: **{categoria.capitalize()}**.\n\n"
                "Ahora configura tu hora de lectura:",
                parse_mode="Markdown"
            )
            # Mostramos el menú de horas automáticamente
            context.args = []
            await programar_horario(update, context)
            
        except Exception:
            await query.edit_message_text("❌ Error guardando categoría.")

    # Caso 2: Eligió Hora
    elif data.startswith("time_"):
        hora = data.replace("time_", "")
        
        if hora == "manual":
            await query.edit_message_text("✏️ Escribe el comando así:\n`/programar 07:30`", parse_mode="Markdown")
            return

        exito = await guardar_y_activar_alarma(chat_id, hora, context)
        if exito:
            await query.edit_message_text(f"✅ ¡Excelente! Te recordaré leer la biblia todos los días a las **{hora}**.", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Hubo un error al guardar la hora.")

# --- 6. RESTAURACIÓN AUTOMÁTICA (Al reiniciar el servidor) ---
async def restaurar_alarmas(application):
    print("🔄 Restaurando alarmas desde la base de datos...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Recuperamos usuarios que tienen hora configurada
        cursor.execute("SELECT telegram_id, hora_recordatorio FROM usuarios WHERE hora_recordatorio IS NOT NULL")
        usuarios = cursor.fetchall()
        conn.close()
        
        count = 0
        for uid, hora_str in usuarios:
            try:
                h, m = map(int, hora_str.split(':'))
                tz = pytz.timezone(ZONA_HORARIA)
                time_to_run = datetime.time(hour=h, minute=m, tzinfo=tz)
                
                application.job_queue.run_daily(enviar_recordatorio, time_to_run, chat_id=uid, name=str(uid))
                count += 1
            except Exception:
                pass # Si una falla, seguimos con las demás
                
        print(f"✅ Se restauraron {count} alarmas programadas.")
        
    except Exception as e:
        print(f"❌ Error restaurando alarmas: {e}")

# --- 7. FUNCIÓN PRINCIPAL ---
def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN: 
        print("Error: Falta TOKEN")
        return

    # Servidor falso en segundo plano
    threading.Thread(target=start_dummy_server, daemon=True).start()
    
    # Configuración de conexión HTTP
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0, http_version="1.1")
    
    # Truco para correr la restauración antes de iniciar
    async def post_init(application):
        await restaurar_alarmas(application)

    # Construimos la aplicación
    app = ApplicationBuilder().token(TOKEN).request(req).post_init(post_init).build()
    
    # Agregamos los manejadores de comandos
    app.add_handler(CommandHandler(["start", "Iniciar"], start))
    app.add_handler(CommandHandler("cita", enviar_cita_random))   # Tabla vieja (random)
    app.add_handler(CommandHandler("programar", programar_horario)) # Tabla nueva (plan)
    app.add_handler(CallbackQueryHandler(manejar_botones))          # Botones

    print("Bot corriendo con Arquitectura Relacional...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
