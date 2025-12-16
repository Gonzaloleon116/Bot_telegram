import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👶 Niño", callback_data="nino"),
        InlineKeyboardButton("🧑 Joven", callback_data="joven"),
        InlineKeyboardButton("👨 Adulto", callback_data="adulto")
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📖 Bienvenido al Bot de Citas Bíblicas\n\n"
        "Elige tu categoría:",
        reply_markup=reply_markup
    )

async def seleccionar_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    categoria = query.data
    await query.edit_message_text(
        f"✅ Categoría seleccionada: {categoria.capitalize()}\n\n"
        "Escribe /cita para recibir una cita bíblica."
    )

def main():
    TOKEN = os.getenv("8431268283:AAFm2P81NdB4nMGn99Ka1mD6BLipHep5Xgw")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(seleccionar_categoria))

    print("Bot corriendo en Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()
