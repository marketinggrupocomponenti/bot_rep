import subprocess
import sys
import os

# --- SISTEMA DE AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
def instalar_dependencias():
    dependencias = ["requests", "beautifulsoup4", "psycopg2-binary", "python-dotenv", "discord.py"]
    for lib in dependencias:
        try:
            if lib == "beautifulsoup4":
                __import__("bs4")
            else:
                __import__(lib.replace("-binary", ""))
        except ImportError:
            print(f"📦 Dependência '{lib}' não encontrada. Instalando...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", lib])
                print(f"✅ '{lib}' instalada com sucesso!")
            except Exception as e:
                print(f"❌ Falha ao instalar '{lib}': {e}")

instalar_dependencias()

# --- IMPORTS ---
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
    sys.exit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- BANCO DE DADOS (COM RECONEXÃO) ---

def get_db_connection():
    url = DATABASE_URL
    if not url: return None
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
                ultima_rep TEXT
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
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
        embed.set_footer(text=f"Executor: {ctx.author.name} (ID: {ctx.author.id})")
        await canal.send(embed=embed)

# --- VERIFICAÇÕES ---

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
    elif cargo_perigoso and cargo_perigoso in membro.roles:
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

# --- EVENTOS ---

@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está ONLINE!')
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

# --- COMANDOS PADRÃO ---

@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Central de Comandos", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação (1h cooldown).", inline=True)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação (1h cooldown).", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver pontos e status.", inline=True)
    embed.add_field(name="🛰️ `!eventos`", value="Ver timers dos mapas.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Ranking global.", inline=True)
    
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator
    if is_staff:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!restart`, `!say`", inline=False)
    
    embed.set_footer(text="Desenvolvido por fugazzeto para ARC Raiders Brasil.")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def rep(ctx, membro: discord.Member):
    if membro == ctx.author or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Alvo inválido.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
    await enviar_log(ctx, f"🌟 **Reputação Positiva**\nDe: {ctx.author.mention}\nPara: {membro.mention}\nNovo Total: `{nova}`", 0x2ecc71)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user) # Adicionado cooldown de 1h
async def neg(ctx, membro: discord.Member):
    if membro == ctx.author or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Alvo inválido.")
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu -1 rep para {membro.mention}!")
    await enviar_log(ctx, f"💢 **Reputação Negativa**\nDe: {ctx.author.mention}\nPara: {membro.mention}\nNovo Total: `{nova}`", 0xe74c3c)
    await verificar_cargos_nivel(ctx, membro, nova)

# --- COMANDOS DE STAFF ---

@bot.command()
@eh_staff()
async def resetar(ctx, membro: discord.Member):
    nova = alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"♻️ Reputação de {membro.mention} foi resetada para 0.")
    await enviar_log(ctx, f"♻️ **Reset de Reputação**\nExecutor: {ctx.author.mention}\nAlvo: {membro.mention}", 0x95a5a6)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def say(ctx, *, mensagem: str):
    await ctx.message.delete()
    await ctx.send(mensagem)

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")
    await enviar_log(ctx, f"🛠️ **Ajuste Manual**\nExecutor: {ctx.author.mention}\nAlvo: {membro.mention}\nValor definido: `{valor}`", 0x3498db)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def restart(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    await enviar_log(ctx, "🔄 O bot foi reiniciado manualmente.")
    os