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

# Executa a verificação antes de qualquer importação pesada
instalar_dependencias()

# --- AGORA OS IMPORTS NORMAIS ---
import discord
from discord.ext import commands
import psycopg2
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
def carregar_config():
    load_dotenv(override=True)
    # Garante que variáveis nulas não quebrem o bot
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

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --- BANCO DE DADOS (COM RECONEXÃO) ---

def get_db_connection():
    url = os.getenv('DATABASE_URL')
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

    # Cargo Perigoso (Negativo)
    if pontos <= -10 and cargo_perigoso:
        if cargo_perigoso not in membro.roles:
            try: await membro.add_roles(cargo_perigoso)
            except: pass
    elif cargo_perigoso and cargo_perigoso in membro.roles:
        try: await membro.remove_roles(cargo_perigoso)
        except: pass

    # Cargos Positivos
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

@bot.command()
async def eventos(ctx):
    url = "https://metaforge.app/arc-raiders/event-timers"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        msg = await ctx.send("🛰️ Sintonizando radar da ARC...")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return await msg.edit(content=f"❌ Metaforge fora de alcance (Status: {response.status_code})")

        soup = BeautifulSoup(response.content, 'html.parser')
        cards = soup.find_all(class_='event-card') or soup.select('.timer-card')

        embed = discord.Embed(title="🛰️ Timers de Eventos - ARC Raiders Brasil", color=0x2ecc71, url=url)

        if not cards:
            embed.description = "⚠️ Sensores bloqueados por JavaScript.\n\n[Clique aqui para ver os timers no site oficial](https://metaforge.app/arc-raiders/event-timers)"
        else:
            for card in cards[:6]:
                try:
                    nome = card.find(['h3', 'span']).text.strip()
                    tempo = card.find(class_='timer').text.strip()
                    embed.add_field(name=f"📍 {nome}", value=f"⏳ `{tempo}`", inline=True)
                except: continue

        embed.set_footer(text="Fonte: Metaforge.app")
        await msg.edit(content=None, embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Falha no radar: {e}")

# --- COMANDOS PADRÃO ---

@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Comandos do Bot", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação.", inline=True)
    embed.add_field(name="💢 `!neg @membro` (Staff)", value="Dá -1 de reputação.", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver pontos.", inline=True)
    embed.add_field(name="🛰️ `!eventos`", value="Ver timers dos mapas.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Ranking global.", inline=True)
    
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator
    if is_staff:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!restart`", inline=False)
    
    embed.set_footer(text="Desenvolvido por fugazzeto para ARC Raiders Brasil.")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def rep(ctx, membro: discord.Member):
    if membro == ctx.author or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação a si mesmo ou bots.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def neg(ctx, membro: discord.Member):
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu -1 rep para {membro.mention}!")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    if not conn: return await ctx.send("❌ Banco de dados offline.")
    cursor = conn.cursor()
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res = cursor.fetchone()
    pontos = res[0] if res else 0
    cursor.close()
    conn.close()
    
    status = "🥇" if pontos >= 100 else "🥈" if pontos >= 50 else "🥉" if pontos >= 10 else "👍"
    if pontos <= -10: status = "💀"
    
    embed = discord.Embed(title=f"Perfil de {membro.display_name}", color=0x3498db)
    embed.add_field(name="Reputação", value=f"{status} **{pontos}** pontos")
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    lb = cursor.fetchall()
    cursor.close()
    conn.close()
    msg = "🏆 **RANKING DE REPUTAÇÃO**\n" + "\n".join([f"`{i}.` <@{uid}> - **{r}**" for i, (uid, r) in enumerate(lb, 1)])
    await ctx.send(msg)

@bot.command()
@eh_staff()
async def restart(ctx):
    await ctx.send("🔄 Reiniciando bot...")
    os.execv(sys.executable, [sys.executable, __file__, str(ctx.channel.id)])

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Aguarde {int(error.retry_after)}s.")

bot.run(TOKEN)