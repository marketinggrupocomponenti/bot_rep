import os
import sys
import discord
from discord.ext import commands
import psycopg2
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io # Adiciona isto no topo do ficheiro, junto aos outros imports

# --- CONFIGURAÇÕES ---
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
# IDs ou nomes dos canais permitidos
CANAIS_PERMITIDOS = [1434310955004592360, 1412423356946317350]

if not TOKEN:
    print("❌ ERRO: DISCORD_TOKEN não encontrado!")
    sys.exit(1)

# --- CONFIGURAÇÃO DO BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- BANCO DE DADOS ---
def get_db_connection():
    if not DATABASE_URL: return None
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
    try: return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except: return None

def setup_db():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (id BIGINT PRIMARY KEY, rep INTEGER DEFAULT 0, ultima_rep TIMESTAMP)''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
        user_id BIGINT PRIMARY KEY,
        motivo TEXT,
        staff_id BIGINT,
        data_blacklist TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        cursor.close()
        conn.close()

def alterar_rep(user_id, quantidade, definir=False):
    conn = get_db_connection()
    if not conn: return 0
    cursor = conn.cursor()
    if definir:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    else:
        cursor.execute('INSERT INTO usuarios (id, rep) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET rep = usuarios.rep + EXCLUDED.rep RETURNING rep', (user_id, quantidade))
    res = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return res[0] if res else 0

# --- SISTEMA DE LOGS ---
async def enviar_log(ctx, mensagem, cor=0xffa500):
    if LOG_CHANNEL_ID == 0: return
    canal = bot.get_channel(LOG_CHANNEL_ID)
    if canal:
        embed = discord.Embed(title="🛰️ Registro de Atividade", description=mensagem, color=cor, timestamp=datetime.now())
        embed.set_footer(text=f"Executor: {ctx.author.name}")
        await canal.send(embed=embed)

# --- CHECKS (VERIFICAÇÕES) ---

@bot.check
async def verificar_canal(ctx):
    if isinstance(ctx.channel, discord.DMChannel): 
        return False
    
    # IDs das suas configurações
    ID_FORUM_TROCA = 1434310955004592360
    ID_CANAL_STAFF = 1412423356946317350

    # Verificações de Identidade
    is_admin = ctx.author.guild_permissions.administrator
    is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
    
    # Identificar se o canal atual é uma Thread (Post de Fórum)
    # Se for thread, o parent_id é o ID do Canal de Fórum
    parent_id = getattr(ctx.channel, "parent_id", None)
    
    no_forum_troca = (ctx.channel.id == ID_FORUM_TROCA or parent_id == ID_FORUM_TROCA)
    no_canal_staff = (ctx.channel.id == ID_CANAL_STAFF or parent_id == ID_CANAL_STAFF)

    # REGRA:
    # 1. Staff (Admin/Mod) pode usar no Fórum (em tópicos ou na raiz) e no canal de Staff
    if is_admin or is_mod:
        return no_forum_troca or no_canal_staff
    
    # 2. Membros Comuns: Só podem usar se estiverem DENTRO de um tópico do Fórum de Trocas
    return no_forum_troca

# 2. Check de Staff
def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin: return True
        await ctx.send("❌ Você não tem permissão para usar este comando.", delete_after=5)
        return False
    return commands.check(predicate)

# 3. Check para ignorar cooldown
def ignora_cooldown_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin:
            ctx.command.reset_cooldown(ctx)
        return True
    return commands.check(predicate)

# --- SISTEMA DE CARGOS ---
async def verificar_cargos_nivel(ctx, membro, pontos):
    niveis = [{"limite": 100, "nome": "trocador oficial"}, {"limite": 50, "nome": "trocador confiavel"}, {"limite": 10, "nome": "trocador iniciante"}]
    cargo_perigoso = discord.utils.get(ctx.guild.roles, name="trocador perigoso")
    if pontos <= -10 and cargo_perigoso:
        if cargo_perigoso not in membro.roles: await membro.add_roles(cargo_perigoso)
    elif cargo_perigoso and cargo_perigoso in membro.roles and pontos > -10:
        await membro.remove_roles(cargo_perigoso)
    for nivel in niveis:
        cargo = discord.utils.get(ctx.guild.roles, name=nivel["nome"])
        if cargo:
            if pontos >= nivel["limite"] and cargo not in membro.roles: await membro.add_roles(cargo)
            elif pontos < nivel["limite"] and cargo in membro.roles: await membro.remove_roles(cargo)

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    print(f'✅ {bot.user.name} está ONLINE!')
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

@bot.event
async def on_thread_create(thread):
    # ID do teu fórum de trocas
    ID_FORUM_TROCA = 1434310955004592360

    # 1. Pequeno delay para garantir que a thread está estável
    import asyncio
    await asyncio.sleep(2)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT motivo FROM blacklist WHERE user_id = %s', (thread.owner_id,))
    blacklisted = cursor.fetchone()
    conn.close()

    if blacklisted:
        await thread.send(f"🚨 **ALERTA DE SEGURANÇA** 🚨\n{thread.owner.mention}, você está na **LISTA NEGRA** deste servidor e não tem permissão para realizar trocas.\n**Motivo:** {blacklisted[0]}")
        # Opcional: Trancar o tópico na hora
        await thread.edit(locked=True, archived=True)
        return

    # 2. Verifica se o pai da thread é o fórum correto
    # Usamos o ID do pai ou tentamos buscar o ID se o objeto estiver incompleto
    parent_id = getattr(thread, "parent_id", None)

    if parent_id == ID_FORUM_TROCA:
        try:
            # 3. Se o Bot não for o dono (para evitar loop) e for um post novo
            embed = discord.Embed(
            title="📦 Nova Troca Iniciada!",
            description=(
                f"Olá {thread.owner.mention}, bem-vindo ao sistema de trocas!\n\n"
                "**Dicas de Segurança:**\n"
                "1. Verifique a reputação de alguém usando o comando `!perfil @membro` antes fazer uma troca.\n"
                "2. Use o comando `!rep @membro` apenas após a troca ser concluída com sucesso.\n"
                "3. Use o comando `!finalizar` para finalizar sua troca e fecharmos seu tópico.\n"
                "4. Se por acaso for scammado, abra um ticket acionando nossos mods imediatamente e use o comando `!neg @membro` para negativar o raider.\n\n"
                "***RMT: Compra e venda de itens com dinheiro real é PROIBIDO e passivo de banimento aqui e no jogo, cuida.***\n"
            ),
            color=discord.Color.blue()
            )
            embed.set_footer(text="ARC Raiders Brasil - Sistema de Trocas e Reputação")
            
            await thread.send(embed=embed)
            print(f"✅ Mensagem de boas-vindas enviada no tópico: {thread.name}")
            
        except Exception as e:
            print(f"❌ Erro ao enviar boas-vindas no tópico {thread.id}: {e}")

# --- COMANDOS ---
@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Lista de Comandos", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação.", inline=True)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação.", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação.", inline=True)
    embed.add_field(name="✅ `!finalizar`", value="Finaliza uma troca e fecha o tópico.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Ver o ranking dos 10 melhores trocadores.", inline=True)
    
    if any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!say`", inline=False)
    
    embed.set_footer(text="Developer: fugazzeto | Sponsor: ! Gio | ARC Raiders Brasil")
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn:
        return await ctx.send("❌ Erro ao conectar ao banco de dados.")
    
    cursor = conn.cursor()
    # Limitamos a busca aos 10 melhores
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()

    if not usuarios:
        return await ctx.send("⚠️ O ranking ainda está vazio.")

    descricao = ""
    for i, (uid, pontos) in enumerate(usuarios, 1):
        # Tenta buscar o nome do usuário
        user = bot.get_user(uid)
        nome = user.name if user else f"Usuário Antigo ({uid})"
        
        # Formatação visual do ranking
        if i == 1:
            prefixo = "🥇 "
        elif i == 2:
            prefixo = "🥈 "
        elif i == 3:
            prefixo = "🥉 "
        else:
            prefixo = f"**{i}.** "

        descricao += f"{prefixo}{nome} — `{pontos} pts` \n"

    embed = discord.Embed(
        title="🏆 Top 10 - Maiores Reputações",
        description=descricao,
        color=0xf1c40f, # Cor dourada
        timestamp=datetime.now()
    )
    embed.set_footer(text="ARC Raiders Brasil | Ranking de Confiança")
    
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def rep(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Você não pode dar reputação para si mesmo ou bots.")
    nova = alterar_rep(membro.id, 1)
    await ctx.send(f"🌟 {ctx.author.mention} deu +1 rep para {membro.mention}!")
    await enviar_log(ctx, f"🌟 **Reputação Positiva**\nPara: {membro.mention}\nTotal: `{nova}`", 0x2ecc71)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def finalizar(ctx):
    """Exclui permanentemente o tópico do fórum de trocas."""
    
    # ID do teu fórum de trocas
    ID_FORUM_TROCA = 1434310955004592360 

    # 1. Verifica se o canal atual é uma Thread (post de fórum)
    if not isinstance(ctx.channel, discord.Thread):
        return await ctx.send("❌ Este comando só funciona dentro do fórum trocas-de-itens.", delete_after=5)

    # 2. Verifica se o "pai" dessa thread é o Fórum de Trocas
    if ctx.channel.parent_id != ID_FORUM_TROCA:
        return await ctx.send("❌ Este comando só pode ser utilizado no fórum de trocas.", delete_after=5)

    # Verificações de permissão (Dono do post ou Staff)
    is_owner = ctx.author.id == ctx.channel.owner_id
    is_staff = any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator

    if is_owner or is_staff:
        # Aviso antes de deletar (já que a exclusão é irreversível)
        await ctx.send("⚠️ **Troca finalizada.** Este tópico será **EXCLUÍDO** permanentemente em 5 segundos..")
        
        import asyncio
        await asyncio.sleep(5)
        
        try:
            nome_topico = ctx.channel.name # Guarda o nome para o log antes de apagar
            
            # Registro no canal de Logs ANTES de deletar para não perder a referência
            await enviar_log(ctx, f"🗑️ **Tópico Excluído**\nPost: `{nome_topico}`\nExecutor: {ctx.author.mention}", 0xe74c3c)
            
            # Exclui o tópico permanentemente
            await ctx.channel.delete(reason=f"Finalizado por {ctx.author.name}")
            
        except Exception as e:
            print(f"Erro ao excluir tópico: {e}")
            await ctx.send("❌ Ocorreu um erro ao tentar excluir o tópico.")
    else:
        await ctx.send("❌ Apenas o dono do post ou a staff podem finalizar e excluir esta troca.", delete_after=5)

@bot.command()
@commands.cooldown(1, 7200, commands.BucketType.user)
@ignora_cooldown_staff()
async def neg(ctx, membro: discord.Member):
    if membro.id == ctx.author.id or membro.bot:
        ctx.command.reset_cooldown(ctx)
        return await ctx.send("❌ Comando inválido.")
    nova = alterar_rep(membro.id, -1)
    await ctx.send(f"💢 {ctx.author.mention} deu -1 rep para {membro.mention}!")
    await enviar_log(ctx, f"💢 **Reputação Negativa**\nPara: {membro.mention}\nTotal: `{nova}`", 0xe74c3c)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    membro = membro or ctx.author
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Busca Reputação
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res_rep = cursor.fetchone()
    pontos = res_rep[0] if res_rep else 0
    
    # Busca se está na Blacklist
    cursor.execute('SELECT motivo FROM blacklist WHERE user_id = %s', (membro.id,))
    res_black = cursor.fetchone()
    conn.close()
    
    if res_black:
        embed = discord.Embed(title=f"⚠️ PERFIL DE RISCO: {membro.name} ⚠️", color=0xff0000)
        embed.description = f"🚨 **ESTE USUÁRIO ESTÁ NA LISTA NEGRA!**\n**Motivo:** {res_black[0]}"
        embed.add_field(name="Reputação", value="BLOQUEADA", inline=True)
    else:
        status = "Neutro"
        if pontos >= 100: status = "Trocador Oficial 💎"
        elif pontos >= 50: status = "Trocador Confiável ✅"
        elif pontos >= 10: status = "Trocador Iniciante ✅"
        elif pontos <= -10: status = "Trocador Perigoso ❌"

        embed = discord.Embed(title=f"Perfil de {membro.name}", color=0x2ecc71)
        embed.add_field(name="Pontos de Reputação", value=f"`{pontos}`", inline=True)
        embed.add_field(name="Status", value=status, inline=True)
    
    embed.set_thumbnail(url=membro.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
@eh_staff()
async def setrep(ctx, membro: discord.Member, valor: int):
    nova = alterar_rep(membro.id, valor, definir=True)
    await ctx.send(f"✅ Rep de {membro.mention} definida para `{valor}`.")
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def resetar(ctx, membro: discord.Member):
    """Reseta a reputação de um membro para 0."""
    nova = alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"♻️ A reputação de {membro.mention} foi resetada para 0.")
    await enviar_log(ctx, f"♻️ **Reset de Reputação**\nAlvo: {membro.mention}", 0x95a5a6)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def say(ctx, canal_ou_msg=None, *, mensagem: str = None):
    """
    Faz o bot falar.
    Uso: !say Mensagem (no canal atual)
    Uso: !say #canal Mensagem (em outro canal)
    """
    # 1. Caso: !say #canal Mensagem
    # O discord.py converte menções de canal automaticamente se usarmos Union ou checagem manual
    if canal_ou_msg and canal_ou_msg.startswith('<#'):
        try:
            target_channel = await commands.TextChannelConverter().convert(ctx, canal_ou_msg)
            msg_final = mensagem
        except:
            target_channel = ctx.channel
            msg_final = f"{canal_ou_msg} {mensagem or ''}"
    
    # 2. Caso: !say Mensagem (no canal atual)
    else:
        target_channel = ctx.channel
        # Junta o primeiro argumento com o resto da mensagem
        msg_final = f"{canal_ou_msg} {mensagem or ''}".strip()

    if not msg_final or msg_final == "None":
        return await ctx.send("❌ Você precisa digitar uma mensagem!", delete_after=5)

    try:
        await ctx.message.delete()
    except:
        pass

    await target_channel.send(msg_final)
    await enviar_log(ctx, f"📢 **Comando !say**\n**Canal:** {target_channel.mention}\n**Conteúdo:** {msg_final}", 0x9b59b6)

@bot.command()
@eh_staff()
async def denunciar(ctx, membro: discord.Member, *, motivo: str):
    """Adiciona um usuário à lista negra de trocas."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO blacklist (user_id, motivo, staff_id) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET motivo = EXCLUDED.motivo
        ''', (membro.id, motivo, ctx.author.id))
        conn.commit()
        
        # Opcional: Remover todos os pontos de rep do scammer
        alterar_rep(membro.id, -999, definir=True)
        
        embed = discord.Embed(title="🚫 Usuário Banido das Trocas", color=0xff0000)
        embed.add_field(name="Membro", value=membro.mention, inline=True)
        embed.add_field(name="Motivo", value=motivo, inline=True)
        embed.set_footer(text="Este usuário foi marcado como PERIGOSO.")
        
        await ctx.send(embed=embed)
        await enviar_log(ctx, f"🚫 **BLACK-LIST**\nAlvo: {membro.mention}\nMotivo: {motivo}", 0xff0000)
        
    except Exception as e:
        await ctx.send(f"❌ Erro ao processar denúncia: {e}")
    finally:
        conn.close()

@bot.command()
@eh_staff()
async def perdoar(ctx, membro: discord.Member):
    """Remove um usuário da lista negra."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM blacklist WHERE user_id = %s', (membro.id,))
    conn.commit()
    conn.close()
    
    await ctx.send(f"✅ {membro.mention} foi removido da lista negra.")
    await enviar_log(ctx, f"🛡️ **PERDÃO**\nAlvo: {membro.mention} removido da blacklist.", 0x2ecc71)

@bot.command()
@eh_staff()
async def backup(ctx):
    """Gera um ficheiro de texto com toda a base de dados de reputação."""
    await ctx.send("📂 A gerar backup da base de dados... Por favor, aguarda.")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Backup de Reputação
        cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC')
        usuarios = cursor.fetchall()
        
        # 2. Backup de Blacklist
        cursor.execute('SELECT user_id, motivo FROM blacklist')
        blacklisted = cursor.fetchall()
        
        conn.close()

        # Criar o conteúdo do ficheiro em memória
        buffer = io.StringIO()
        buffer.write(f"--- BACKUP REPUTAÇÃO ARC RAIDERS BRASIL ({datetime.now().strftime('%d/%m/%Y %H:%M')}) ---\n\n")
        
        buffer.write("🌟 RANKING DE REPUTAÇÃO:\n")
        for uid, pts in usuarios:
            user = bot.get_user(uid)
            nome = user.name if user else f"Desconhecido({uid})"
            buffer.write(f"ID: {uid} | Nome: {nome} | Pontos: {pts}\n")
            
        buffer.write("\n" + "="*50 + "\n\n")
        
        buffer.write("🚫 LISTA NEGRA (BLACKLIST):\n")
        if not blacklisted:
            buffer.write("Nenhum utilizador na lista negra.\n")
        for uid, motivo in blacklisted:
            user = bot.get_user(uid)
            nome = user.name if user else f"Desconhecido({uid})"
            buffer.write(f"ID: {uid} | Nome: {nome} | Motivo: {motivo}\n")

        buffer.seek(0)
        
        # Enviar como ficheiro
        file = discord.File(fp=buffer, filename=f"backup_rep_{datetime.now().strftime('%d_%m_%Y')}.txt")
        await ctx.send(content="✅ Aqui está o backup completo do sistema:", file=file)
        
        await enviar_log(ctx, "📂 **Backup do Sistema** realizado com sucesso.", 0x9b59b6)

    except Exception as e:
        await ctx.send(f"❌ Erro ao gerar backup: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutos = int(error.retry_after // 60)
        await ctx.send(f"⏳ Aguarde {minutos} minutos.", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        # Opcional: Avisar que o canal está errado
        if not ctx.author.guild_permissions.administrator:
             await ctx.send(f"❌ {ctx.author.mention}, este comando não pode ser usado aqui.", delete_after=7)

from discord.ext import tasks

@tasks.loop(minutes=10)
async def manter_banco_vivo():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1") # Uma query simples só para manter o túnel ativo
        conn.close()
        print("ping no banco: OK")
    except Exception as e:
        print(f"Erro no ping do banco: {e}")

@bot.event
async def on_ready():
    setup_db()
    manter_banco_vivo.start() # Inicia o loop quando o bot liga
    print(f"✅ {bot.user.name} Online e Banco Protegido")

if __name__ == "__main__":
    setup_db()
    bot.run(TOKEN)