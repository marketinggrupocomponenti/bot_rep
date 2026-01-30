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

# --- FUNÇÃO AUXILIAR DE CARGOS ---

async def verificar_cargos_nivel(ctx, membro, pontos):
    """Verifica e atribui cargos baseados na pontuação"""
    niveis = [
        {"limite": 100, "nome": "trocador oficial"},
        {"limite": 50, "nome": "trocador confiavel"},
        {"limite": 10, "nome": "trocador iniciante"}
    ]
    
    for nivel in niveis:
        if pontos >= nivel["limite"]:
            cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
            if cargo and cargo not in membro.roles:
                try:
                    await membro.add_roles(cargo)
                    await ctx.send(f"🎉 {membro.mention} subiu de nível e agora é um **{cargo.name}**!")
                except Exception as e:
                    print(f"Erro ao adicionar cargo {nivel['nome']}: {e}")
            break # Adiciona apenas o cargo do nível mais alto atingido

# --- EVENTOS ---

@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} online | Sistema de Medalhas Ativado!')
    await bot.change_presence(activity=discord.Game(name="Digite: !ajuda"))

# --- COMANDOS PÚBLICOS ---

@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Guia de Comandos - ARC Raiders Brasil", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação (1 uso por hora).", inline=False)
    embed.add_field(name="👤 `!perfil @membro`", value="Consulta a reputação de alguém.", inline=False)
    embed.add_field(name="🏆 `!top`", value="Ranking dos 10 melhores.", inline=False)
    embed.add_field(name="🎖️ Níveis", value="🥉 10: Iniciante | 🥈 50: Confiável | 🥇 100: Oficial", inline=False)
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

    # Sistema de Logs
    try:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(title="📈 Registro de Reputação", color=discord.Color.dark_green())
            log_embed.add_field(name="Doador", value=f"{ctx.author.mention}\n`{ctx.author.name}`", inline=True)
            log_embed.add_field(name="Recebeu", value=f"{membro.mention}\n`{membro.name}`", inline=True)
            log_embed.add_field(name="Nova Pontuação", value=f"✨ `{nova_pontuacao}` pontos", inline=False)
            log_embed.timestamp = ctx.message.created_at
            await log_channel.send(embed=log_embed)
    except: pass

    # Verifica se ganhou medalha/cargo novo
    await verificar_cargos_nivel(ctx, membro, nova_pontuacao)

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
    
    # Define a medalha para o perfil
    medalha = "🥚"
    if pontos >= 100: medalha = "🥇"
    elif pontos >= 50: medalha = "🥈"
    elif pontos >= 10: medalha = "🥉"

    embed = discord.Embed(title=f"Perfil de {membro.display_name}", color=discord.Color.green())
    embed.add_field(name="Reputação Atual", value=f"{medalha} `{pontos}` pontos")
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
        medalha = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "✨"
        desc += f"`#{i:02d}` {medalha} **{nome}** — {pontos} reps\n"
    embed.description = desc
    await ctx.send(embed=embed)

# --- COMANDOS DE STAFF ---

@bot.command()
@commands.has_permissions(manage_messages=True)
async def setrep(ctx, membro: discord.Member, valor: int):
    nova_pontuacao = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Reputação de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova_pontuacao)

@bot.command()
@commands.has_permissions(administrator=True)
async def resetar(ctx, membro: discord.Member):
    alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"⚠️ A reputação de {membro.mention} foi resetada.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        tempo = str(timedelta(seconds=int(error.retry_after)))
        return await ctx.send(f"⏳ Aguarde `{tempo}`.", delete_after=5)
    if isinstance(error, commands.CommandNotFound): return
    print(f"Erro: {error}")

bot.run(TOKEN)