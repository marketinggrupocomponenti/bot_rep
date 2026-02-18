import os
import sys
import discord
from discord.ext import commands
import psycopg2
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
def carregar_config():
    load_dotenv(override=True)
    # No Railway, as variáveis vêm do painel. Se local, tenta carregar o .env
    if not os.getenv('DISCORD_TOKEN'):
        diretorio_script = os.path.dirname(os.path.abspath(__file__))
        caminho_env = os.path.join(diretorio_script, '.env')
        if os.path.exists(caminho_env):
            with open(caminho_env, "r", encoding="utf-8") as f:
                for linha in f:
                    if "=" in linha and not linha.startswith("#"):
                        k, v = linha.split("=", 1)
                        os.environ[k.strip()] = v.strip().replace('"', '').replace("'", "")

carregar_config()

TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit(1)

# --- CONFIGURAÇÃO DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

CANAIS_PERMITIDOS = [1412423356946317350, 1434310955004592360]

# --- BANCO DE DADOS ---
def get_db_connection():
    if not DATABASE_URL: 
        print("⚠️ DATABASE_URL não configurada.")
        return None
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    try:
        return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except Exception as e:
        print(f"⚠️ Erro ao conectar no Banco: {e}")
        return None

def setup_db():
    conn = get_db_connection()
    if conn is None: return
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id BIGINT PRIMARY KEY,
                rep INTEGER DEFAULT 0,
                ultima_rep TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Banco de dados pronto.")
    except Exception as e:
        print(f"❌ Erro no Setup do Banco: {e}")

def alterar_rep(user_id, quantidade, definir=False):
    conn = get_db_connection()
    if conn is None: return 0
    try:
        cursor = conn.cursor()
        if definir:
            cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = EXCLUDED.rep RETURNING rep', (user_id, quantidade))
        else:
            cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep RETURNING rep', (user_id, quantidade))
        res = cursor.fetchone()
        nova_pontuacao = res[0] if res else 0
        conn.commit()
        cursor.close()
        conn.close()
        return nova_pontuacao
    except Exception as e:
        print(f"❌ Erro ao alterar rep: {e}")
        return 0

# --- SISTEMA DE LOGS ---
async def enviar_log(ctx, mensagem, cor=0xffa500):
    if LOG_CHANNEL_ID == 0: return
    canal = bot.get_channel(LOG_CHANNEL_ID)
    if canal:
        embed = discord.Embed(title="🛰️ Registro de Atividade", description=mensagem, color=cor, timestamp=datetime.now())
        embed.set_footer(text=f"Executor: {ctx.author.name}")
        await canal.send(embed=embed)

# --- VERIFICAÇÕES DE STAFF ---
def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin: return True
        await ctx.send("❌ Você não tem permissão para usar este comando.")
        return False
    return commands.check(predicate)

async def verificar_cargos_nivel(ctx, membro, pontos):
    niveis = [
        {"limite": 100, "nome": "trocador oficial"},
        {"limite": 50, "nome": "trocador confiavel"},
        {"limite": 10, "nome": "trocador iniciante"}
    ]
    cargo_perigoso = discord.utils.get(ctx.guild.roles, name="trocador perigoso")

    if pontos <= -10 and cargo_perigoso:
        if cargo_perigoso not in membro.roles:
            try: await membro.add_roles(cargo_perigoso)
            except: pass
    elif cargo_perigoso and cargo_perigoso in membro.roles and pontos > -10:
        try: await membro.remove_roles(cargo_perigoso)
        except: pass

    for nivel in niveis:
        cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
        if cargo:
            if pontos >= nivel["limite"] and cargo not in membro.roles:
                try: await membro.add_roles(cargo)
                except: pass
            elif pontos < nivel["limite"] and cargo in membro.roles:
                try: await membro.remove_roles(cargo)
                except: pass

@bot.check
async def verificar_canal(ctx):
    # Se for mensagem direta (DM), bloqueia (opcional)
    if isinstance(ctx.channel, discord.DMChannel):
        return False

    # Verifica se o canal atual está na lista de permitidos
    # ou se o usuário tem permissão de Administrador (para evitar que a staff fique presa)
    is_canal_permitido = ctx.channel.name in CANAIS_PERMITIDOS
    is_admin = ctx.author.guild_permissions.administrator

    if is_canal_permitido or is_admin:
        return True
    
    # Mensagem opcional de aviso (cuidado para não poluir canais errados)
    # await ctx.send(f"❌ {ctx.author.mention}, este comando só pode ser usado em #troca-de-itens.", delete_after=5)
    return False

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está ONLINE!')
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

# --- COMANDOS ---
@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Central de Comandos", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação (1h cooldown).", inline=True)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação (1h cooldown).", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação e medalha.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Melhores trocadores.", inline=True)
    
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator
    if is_staff:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!restart`, `!say`", inline=False)
    
    embed.set_footer(text="Desenvolvido por fugazzeto para ARC Raiders Brasil.")
    await ctx.send(embed=embed)

# --- COMANDO REP (POSITIVA) ---
@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff() # <--- Adicione aqui
async def rep(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação para si mesmo ou bots.")
    
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
    await enviar_log(ctx, f"🌟 **Reputação Positiva**\nPara: {membro.mention}\nNovo Total: `{nova}`", 0x2ecc71)
    await verificar_cargos_nivel(ctx, membro, nova)

# --- COMANDO NEG (NEGATIVA) ---
@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff() # <--- Adicione aqui
async def neg(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Alvo inválido.")
    
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu -1 rep para {membro.mention}!")
    await enviar_log(ctx, f"💢 **Reputação Negativa**\nPara: {membro.mention}\nNovo Total: `{nova}`", 0xe74c3c)
    await verificar_cargos_nivel(ctx, membro, nova)

# --- TRATAMENTO DE ERRO DE COOLDOWN ---
@rep.error
@neg.error
async def cooldown_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        # Ignora silenciosamente se o comando for usado no canal errado
        return
    if isinstance(error, commands.CommandOnCooldown):
        minutos_restantes = int(error.retry_after // 60)
        horas = minutos_restantes // 60
        minutos = minutos_restantes % 60
        
        msg_tempo = f"{horas}h e {minutos}min" if horas > 0 else f"{minutos} minutos"
        await ctx.send(f"⏳ {ctx.author.mention}, aguarde **{msg_tempo}** para usar este comando novamente.", delete_after=10)
    else:
        # Se for outro erro (ex: membro não encontrado), o bot avisa
        await ctx.send(f"❌ Ocorreu um erro: {error}", delete_after=5)

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res = cursor.fetchone()
    pontos = res[0] if res else 0
    cursor.close()
    conn.close()
    
    status = "Neutro"
    if pontos >= 100: status = "Trocador Oficial 💎"
    elif pontos >= 50: status = "Trocador Confiável ✅"
    elif pontos <= -10: status = "Trocador Perigoso ❌"

    embed = discord.Embed(title=f"Perfil de {membro.name}", color=discord.Color.gold())
    embed.add_field(name="Pontos de Reputação", value=f"`{pontos}`", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.set_thumbnail(url=membro.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()

    if not usuarios:
        return await ctx.send("O ranking está vazio.")

    lista = ""
    for i, (uid, pontos) in enumerate(usuarios, 1):
        user = bot.get_user(uid)
        nome = user.name if user else f"Usuário {uid}"
        lista += f"**{i}.** {nome} — `{pontos} pts` \n"

    embed = discord.Embed(title="🏆 Top 10 Reputação", description=lista, color=0xf1c40f)
    await ctx.send(embed=embed)

# --- COMANDOS DE STAFF ---

@bot.command()
@eh_staff()
async def say(ctx, *, mensagem: str):
    """Faz o bot falar uma mensagem e apaga o comando do autor."""
    await ctx.message.delete()
    await ctx.send(mensagem)

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")
    await enviar_log(ctx, f"🛠️ **Ajuste Manual**\nAlvo: {membro.mention}\nValor: `{valor}`", 0x3498db)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def resetar(ctx, membro: discord.Member):
    nova = alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"♻️ Reputação de {membro.mention} foi resetada.")
    await enviar_log(ctx, f"♻️ **Reset de Reputação**\nAlvo: {membro.mention}", 0x95a5a6)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def restart(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    sys.exit(0)

def ignora_cooldown_staff():
    async def predicate(ctx):
        # Verifica se é admin ou tem o cargo "mods"
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        
        if is_mod or is_admin:
            # Se for staff, resetamos o cooldown do comando atual para este usuário
            ctx.command.reset_cooldown(ctx)
        return True
    return commands.check(predicate)

# --- INICIALIZAÇÃO FINAL ---
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Falha crítica ao iniciar o bot: {e}")