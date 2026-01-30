import discord
from discord.ext import commands
import os
import psycopg2
from dotenv import load_dotenv
from datetime import timedelta

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
# ID do canal de log definido diretamente
LOG_CHANNEL_ID = 1433136439456956576 

# Configuração de Intenções
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --- BANCO DE DADOS POSTGRESQL ---

def get_db_connection():
    url = os.getenv('DATABASE_URL')
    if not url: return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    try:
        return psycopg2.connect(url, sslmode='require')
    except Exception as e:
        print(f"❌ Erro banco: {e}")
        return None

def setup_db():
    conn = get_db_connection()
    if conn is None: return
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id BIGINT PRIMARY KEY,
            rep INTEGER DEFAULT 0,
            ultima_rep TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

def alterar_rep(user_id, quantidade, definir=False):
    conn = get_db_connection()
    if conn is None: return 0
    cursor = conn.cursor()
    if definir:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    else:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    nova_pontuacao = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return nova_pontuacao

# --- EVENTOS ---

@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} online e enviando logs para o canal {LOG_CHANNEL_ID}!')
    await bot.change_presence(activity=discord.Game(name="Digite: !ajuda"))

# --- COMANDOS PÚBLICOS ---

@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Guia de Comandos - ARC Raiders Brasil", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação (1 uso por hora).", inline=False)
    embed.add_field(name="👤 `!perfil @membro`", value="Consulta a reputação de alguém.", inline=False)
    embed.add_field(name="🏆 `!top`", value="Ranking dos 10 melhores.", inline=False)
    if ctx.author.guild_permissions.manage_messages:
        embed.add_field(name="🛠️ Staff", value="`!setrep` e `!resetar`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def rep(ctx, membro: discord.Member):
    if membro == ctx.author:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação para si mesmo!")
    
    if membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Bots não utilizam reputação.")

    nova_pontuacao = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 de reputação para {membro.mention}!")

    # --- SISTEMA DE LOGS ---
    try:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(title="📈 Registro de Reputação", color=discord.Color.dark_green())
            log_embed.add_field(name="Doador", value=f"{ctx.author.mention}\n`{ctx.author.name}`", inline=True)
            log_embed.add_field(name="Recebeu", value=f"{membro.mention}\n`{membro.name}`", inline=True)
            log_embed.add_field(name="Nova Pontuação", value=f"✨ `{nova_pontuacao}` pontos", inline=False)
            log_embed.set_footer(text=f"Enviado do canal: #{ctx.channel.name}")
            log_embed.timestamp = ctx.message.created_at
            await log_channel.send(embed=log_embed)
    except Exception as e:
        print(f"Erro ao enviar log: {e}")

    # Cargo Automático
    if nova_pontuacao >= 100:
        cargo = discord.utils.get(ctx.guild.roles, name="trocador oficial")
        if cargo and cargo not in membro.roles:
            try:
                await membro.add_roles(cargo)
                await ctx.send(f"🎉 {membro.mention} atingiu **100 pontos** e agora é um **{cargo.name}**!")
            except: pass

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res = cursor.fetchone()
    pontos = res[0] if res else 0
    cursor.close()
    conn.close()
    embed = discord.Embed(title=f"Perfil de {membro.display_name}", color=discord.Color.green())
    embed.add_field(name="Reputação Atual", value=f"✨ `{pontos}` pontos")
    embed.set_thumbnail(url=membro.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    leaderboard = cursor.fetchall()
    cursor.close()
    conn.close()
    if not leaderboard: return await ctx.send("Ranking vazio!")
    embed = discord.Embed(title="🏆 Melhores Trocadores", color=discord.Color.gold())
    desc = ""
    for i, (user_id, pontos) in enumerate(leaderboard, 1):
        user = bot.get_user(user_id)
        nome = user.name if user else f"ID:{user_id}"
        desc += f"`#{i:02d}` **{nome}** — {pontos} reps\n"
    embed.description = desc
    await ctx.send(embed=embed)

# --- COMANDOS DE STAFF ---

@bot.command()
@commands.has_permissions(manage_messages=True)
async def setrep(ctx, membro: discord.Member, valor: int):
    alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")

@bot.command()
@commands.has_permissions(administrator=True)
async def resetar(ctx, membro: discord.Member):
    alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"⚠️ Rep de {membro.mention} resetada.")

# --- TRATAMENTO DE ERROS ---

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        tempo = str(timedelta(seconds=int(error.retry_after)))
        return await ctx.send(f"⏳ Aguarde `{tempo}`.", delete_after=5)
    if isinstance(error, commands.CommandNotFound): return
    print(f"Erro: {error}")

bot.run(TOKEN)