import discord
from discord.ext import commands
import os
import psycopg2
from dotenv import load_dotenv
from datetime import timedelta
import sys
import requests
from bs4 import BeautifulSoup  # Importação necessária para o scraping

# --- CARREGAMENTO DE CONFIGURAÇÕES ---
def carregar_config():
    load_dotenv(override=True)
    diretorio_script = os.path.dirname(os.path.abspath(__file__))
    caminho_env = os.path.join(diretorio_script, '.env')
    
    if os.path.exists(caminho_env):
        with open(caminho_env, "r", encoding="utf-8", errors="ignore") as f:
            for linha in f:
                linha = linha.strip()
                if linha and "=" in linha and not linha.startswith("#"):
                    chave, valor = linha.split("=", 1)
                    os.environ[chave.strip()] = valor.strip().replace('"', '').replace("'", "")

carregar_config()

TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 1433136439456956576))

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit()

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
        return psycopg2.connect(url, sslmode='require', connect_timeout=5)
    except:
        try:
            return psycopg2.connect(url, sslmode='disable', connect_timeout=5)
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

# --- FUNÇÕES DE VERIFICAÇÃO ---

def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin:
            return True
        await ctx.send("❌ Você não tem permissão (**mods** ou **admin**) para usar este comando.")
        return False
    return commands.check(predicate)

async def verificar_cargos_nivel(ctx, membro, pontos):
    niveis = [
        {"limite": 100, "nome": "trocador oficial"},
        {"limite": 50, "nome": "trocador confiavel"},
        {"limite": 10, "nome": "trocador iniciante"}
    ]
    
    cargo_perigoso_nome = "trocador perigoso"
    cargo_perigoso = discord.utils.get(ctx.guild.roles, name=cargo_perigoso_nome)

    if pontos <= -10:
        if cargo_perigoso and cargo_perigoso not in membro.roles:
            try:
                await membro.add_roles(cargo_perigoso)
                await ctx.send(f"⚠️ **ATENÇÃO:** {membro.mention} atingiu reputação crítica e recebeu o cargo **{cargo_perigoso_nome}**! 💀")
            except: pass
    else:
        if cargo_perigoso and cargo_perigoso in membro.roles:
            try:
                await membro.remove_roles(cargo_perigoso)
                await ctx.send(f"✅ {membro.mention} não possui mais reputação crítica. Cargo **{cargo_perigoso_nome}** removido.")
            except: pass

    for nivel in niveis:
        cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
        if cargo:
            if pontos < nivel["limite"] and cargo in membro.roles:
                try: await membro.remove_roles(cargo)
                except: pass
            elif pontos >= nivel["limite"] and cargo not in membro.roles:
                try:
                    await membro.add_roles(cargo)
                    await ctx.send(f"🎉 **{membro.display_name}** subiu para **{cargo.name}**!")
                except: pass
                break

# --- EVENTOS ---

@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está ONLINE!')
    await bot.change_presence(activity=discord.Game(name="Digite: !ajuda"))

    if len(sys.argv) > 1:
        try:
            channel_id = int(sys.argv[-1])
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send("✅ **Bot online!** O processo de reinicialização foi concluído.")
            sys.argv.pop()
        except Exception:
            pass

# --- COMANDOS ---

@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Bot de Reputação - ARC Raiders Brasil", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação (1 uso/hora).", inline=False)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação.", inline=False)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação e medalha.", inline=False)
    embed.add_field(name="🏆 `!top`", value="Ranking dos 10 melhores.", inline=False)
    embed.add_field(name="🛰️ `!eventos`", value="Ver cronômetro de eventos do jogo.", inline=False)
    
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator
    if is_staff:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!restart`, `!say`", inline=False)
    
    embed.set_footer(text="Desenvolvido por fugazzeto para ARC Raiders Brasil.")
    await ctx.send(embed=embed)

@bot.command()
async def eventos(ctx):
    """Verifica os eventos de mapa via Metaforge"""
    url_site = "https://metaforge.app/arc-raiders/event-timers"
    # User-Agent para evitar ser bloqueado como bot básico
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

    try:
        msg_espere = await ctx.send("🛰️ Conectando ao Metaforge... Aguarde.")
        response = requests.get(url_site, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return await msg_espere.edit(content="❌ Erro ao acessar o site (Status: " + str(response.status_code) + ").")

        soup = BeautifulSoup(response.content, 'html.parser')
        
        # O seletor abaixo é uma tentativa baseada em estruturas comuns. 
        # Como o site usa React/Next.js, se os cards não aparecerem, o bot avisará o link.
        eventos_cards = soup.find_all('div', class_='event-card') or soup.find_all('div', class_='timer-card')

        embed = discord.Embed(
            title="🛰️ Cronômetro de Eventos - ARC Raiders Brasil",
            description="Informações de eventos em tempo real.",
            color=0x2ecc71,
            url=url_site
        )

        if not eventos_cards:
            embed.description = "⚠️ Não foi possível ler os timers automaticamente (o site usa carregamento dinâmico).\n\n**Confira aqui:** [Metaforge Event Timers](https://metaforge.app/arc-raiders/event-timers)"
        else:
            for card in eventos_cards:
                try:
                    nome = card.find(['h3', 'h4', 'span']).text.strip()
                    tempo = card.find('span', class_='timer').text.strip()
                    embed.add_field(name=f"📍 {nome}", value=f"⏳ `{tempo}`", inline=False)
                except:
                    continue

        embed.set_footer(text="Dados via Metaforge.app")
        await msg_espere.edit(content=None, embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Erro ao buscar eventos: {e}")

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def rep(ctx, membro: discord.Member):
    if membro == ctx.author or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Alvo inválido.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu **+1** de rep para {membro.mention}!")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def neg(ctx, membro: discord.Member):
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu **-1** de rep para {membro.mention}!")
    await verificar_cargos_nivel(ctx, membro, nova)

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
    
    med = "👍"
    if pontos >= 100: med = "🥇"
    elif pontos >= 50: med = "🥈"
    elif pontos >= 10: med = "🥉"
    elif pontos <= -10: med = "💀"
    elif pontos < 0: med = "⚠️"
    await ctx.send(f"👤 {membro.mention} | Status: {med} **{pontos}** pontos.")

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
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Reputação de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def resetar(ctx, membro: discord.Member):
    alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"⚠️ Reputação de {membro.mention} resetada.")

@bot.command()
@eh_staff()
async def restart(ctx):
    await ctx.send("🔄 O bot está sendo reiniciado...")
    os.execv(sys.executable, [sys.executable, __file__, str(ctx.channel.id)])

@bot.command()
@eh_staff()
async def say(ctx, *, mensagem: str):
    try: await ctx.message.delete()
    except: pass
    await ctx.send(mensagem)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Aguarde {int(error.retry_after)}s.")

bot.run(TOKEN)