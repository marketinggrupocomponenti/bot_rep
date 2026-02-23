import os
import sys
import discord
from discord.ext import commands, tasks
import psycopg2
from dotenv import load_dotenv
import requests
from datetime import datetime
import io
import asyncio

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
ID_FORUM_TROCA = 1434310955004592360
ID_CANAL_STAFF = 1412423356946317350
ID_CANAL_RAID = 1412423357600632922

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
        cursor.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id BIGINT PRIMARY KEY, motivo TEXT, staff_id BIGINT, data_blacklist TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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
async def enviar_log(origem, mensagem, cor=0xffa500):
    if LOG_CHANNEL_ID == 0: return
    canal = bot.get_channel(LOG_CHANNEL_ID)
    if canal:
        autor = origem.user if hasattr(origem, 'user') else origem.author
        embed = discord.Embed(title="🛰️ Registro de Atividade", description=mensagem, color=cor, timestamp=datetime.now())
        embed.set_footer(text=f"Executor: {autor.name}")
        await canal.send(embed=embed)

# --- CHECKS (VERIFICAÇÕES) ---
@bot.check
async def verificar_canal(ctx):
    if isinstance(ctx.channel, discord.DMChannel): 
        return False
    is_admin = ctx.author.guild_permissions.administrator
    is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
    parent_id = getattr(ctx.channel, "parent_id", None)
    no_forum_troca = (ctx.channel.id == ID_FORUM_TROCA or parent_id == ID_FORUM_TROCA)
    no_canal_staff = (ctx.channel.id == ID_CANAL_STAFF)
    no_canal_raid = (ctx.channel.id == ID_CANAL_RAID)
    if is_admin or is_mod:
        return no_forum_troca or no_canal_staff or no_canal_raid
    return no_forum_troca or no_canal_raid

def eh_staff():
    async def predicate(ctx):
        is_mod = any(role.name.lower() == "mods" for role in ctx.author.roles)
        is_admin = ctx.author.guild_permissions.administrator
        if is_mod or is_admin: return True
        await ctx.send("❌ Você não tem permissão para usar este comando.", delete_after=5)
        return False
    return commands.check(predicate)

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

# --- CLASSES DE INTERFACE (VIEWS) ---
class FinalizarTrocaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Finalizar e Excluir Tópico", 
        style=discord.ButtonStyle.secondary, 
        emoji="✅",
        custom_id="btn_finalizar_troca"
    )
    async def finalizar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = interaction.channel
        is_owner = interaction.user.id == thread.owner_id
        is_staff = any(role.name.lower() == "mods" for role in interaction.user.roles) or interaction.user.guild_permissions.administrator

        if not (is_owner or is_staff):
            return await interaction.response.send_message("❌ Apenas o dono do post ou a staff podem finalizar esta troca.", ephemeral=True)

        await interaction.response.send_message("⚠️ **Troca finalizada.** Este tópico será **EXCLUÍDO** permanentemente em 5 segundos..")
        await asyncio.sleep(5)
        
        try:
            nome_topico = thread.name
            await enviar_log(interaction, f"🗑️ **Tópico Excluído**\nPost: `{nome_topico}`\nExecutor: {interaction.user.mention}", 0xe74c3c)
            await thread.delete(reason=f"Finalizado por {interaction.user.name}")
        except discord.Forbidden:
            try: await thread.send("❌ **Erro:** O bot precisa da permissão 'Gerenciar Tópicos' para excluir este canal.")
            except: pass
        except Exception as e:
            print(f"❌ Erro ao excluir tópico: {e}")

class VoiceSelectionView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        canais_voz = [1441884973077495808, 1441885994248044605, 1441887071533928540, 1439303187332071594, 1439314706719445218, 1439314014579593607]
        for i, canal_id in enumerate(canais_voz, 1):
            self.add_item(discord.ui.Button(label=f"Sala {i}", url=f"https://discord.com/channels/{guild_id}/{canal_id}", style=discord.ButtonStyle.link))

class RaidView(discord.ui.View):
    def __init__(self, host, mapa, vagas_totais):
        super().__init__(timeout=3600)
        self.host = host
        self.mapa = mapa
        self.vagas_totais = vagas_totais
        self.participantes = [host]

    @discord.ui.button(label="Entrar no Squad", style=discord.ButtonStyle.green, emoji="✋")
    async def entrar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.participantes) >= self.vagas_totais:
            if interaction.user.id == self.host.id:
                view_voz = VoiceSelectionView(interaction.guild.id)
                return await interaction.response.send_message(content=f"🎮 **Sua Raid de {self.mapa.upper()} está pronta!**\n\n**Como convidar seu squad:**\n1. Escolha uma sala abaixo.\n2. Clique com o botão direito nela e selecione **'Copiar Link'**.\n3. Cole o link aqui no canal para seus parceiros entrarem.", view=view_voz, ephemeral=True)
            else:
                return await interaction.response.send_message("❌ Este squad já está completo!", ephemeral=True)
        if interaction.user in self.participantes:
            return await interaction.response.send_message("❌ Você já está neste squad!", ephemeral=True)
        self.participantes.append(interaction.user)
        embed = interaction.message.embeds[0]
        lista_mentions = "\n".join([m.mention for m in self.participantes])
        embed.set_field_at(1, name=f"Membros ({len(self.participantes)}/{self.vagas_totais})", value=lista_mentions, inline=False)
        if len(self.participantes) >= self.vagas_totais:
            button.label = "Squad Completo (Clique p/ Salas)"
            button.style = discord.ButtonStyle.secondary
            embed.color = discord.Color.gold()
        await interaction.message.edit(embed=embed, view=self)
        if len(self.participantes) >= self.vagas_totais and interaction.user.id == self.host.id:
            await interaction.response.send_message(content="✅ **Squad Completo!** Escolha a sala abaixo e envie o link.", view=VoiceSelectionView(interaction.guild.id), ephemeral=True)
        else:
            await interaction.response.send_message("✅ Você entrou no squad!", ephemeral=True)

# --- COMANDOS ---
@bot.command()
async def ajuda(ctx):
    embed = discord.Embed(title="📖 Lista de Comandos", color=discord.Color.blue())
    embed.add_field(name="🌟 `!rep @membro`", value="Dá +1 de reputação.", inline=True)
    embed.add_field(name="💢 `!neg @membro`", value="Dá -1 de reputação.", inline=True)
    embed.add_field(name="👤 `!perfil @membro`", value="Ver reputação.", inline=True)
    embed.add_field(name="📡 `!raid mapa/objetivo 1`", value="Cria uma raid para duo.", inline=True)
    embed.add_field(name="📡 `!raid mapa/objetivo 2`", value="Cria uma raid para trio.", inline=True)
    embed.add_field(name="🏆 `!top`", value="Ver o ranking dos 10 melhores trocadores.", inline=True)
    if any(role.name.lower() == "mods" for role in ctx.author.roles) or ctx.author.guild_permissions.administrator:
        embed.add_field(name="🛠️ Staff", value="`!setrep`, `!resetar`, `!say`, `!backup`, `!denunciar`, `!perdoar`, `!colocar_botao` ", inline=False)
    embed.set_footer(text="Developer: fugazzeto | Sponsor: ! Gio | ARC Raiders Brasil")
    await ctx.send(embed=embed)

@bot.command()
async def raid(ctx, mapa: str = None, vagas: int = None):
    if mapa is None or vagas is None:
        return await ctx.send("❌ Uso: `!raid [mapa/objetivo] [vagas]` (1 para Duo, 2 para Trio)")
    if ctx.channel.id != ID_CANAL_RAID:
        return await ctx.send(f"❌ Use em <#{ID_CANAL_RAID}>.", delete_after=5)
    if vagas < 1 or vagas > 2:
        return await ctx.send("❌ Escolha 1 ou 2 vagas extras.")
    total = vagas + 1
    embed = discord.Embed(title=f"🚨Chamada p/ Raid: {'DUO' if total==2 else 'TRIO'}", color=0x2ecc71)
    embed.add_field(name="📍 Mapa/Objetivo", value=mapa.upper(), inline=True)
    embed.add_field(name=f"Membros (1/{total})", value=f"👤 {ctx.author.mention}", inline=False)
    await ctx.send(embed=embed, view=RaidView(ctx.author, mapa, total))

@bot.command()
async def top(ctx):
    conn = get_db_connection()
    if not conn: return await ctx.send("❌ Erro no banco de dados.")
    cursor = conn.cursor()
    cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC LIMIT 10')
    usuarios = cursor.fetchall()
    conn.close()
    if not usuarios: return await ctx.send("⚠️ O ranking ainda está vazio.")
    descricao = ""
    for i, (uid, pontos) in enumerate(usuarios, 1):
        user = bot.get_user(uid)
        nome = user.name if user else f"Usuário Antigo ({uid})"
        prefixo = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"**{i}.** "
        descricao += f"{prefixo}{nome} — `{pontos} pts` \n"
    embed = discord.Embed(title="🏆 Top 10 - Maiores Reputações", description=descricao, color=0xf1c40f, timestamp=datetime.now())
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
    cursor.execute('SELECT rep FROM usuarios WHERE id = %s', (membro.id,))
    res_rep = cursor.fetchone()
    pontos = res_rep[0] if res_rep else 0
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
    nova = alterar_rep(membro.id, 0, definir=True)
    await ctx.send(f"♻️ A reputação de {membro.mention} foi resetada para 0.")
    await enviar_log(ctx, f"♻️ **Reset de Reputação**\nAlvo: {membro.mention}", 0x95a5a6)
    await verificar_cargos_nivel(ctx, membro, nova)

@bot.command()
@eh_staff()
async def colocar_botao(ctx):
    if isinstance(ctx.channel, discord.Thread):
        await ctx.send("Clique abaixo para finalizar esta troca:", view=FinalizarTrocaView())
    else:
        await ctx.send("Este comando só funciona dentro de um tópico!")

@bot.command()
@eh_staff()
async def say(ctx, canal_ou_msg=None, *, mensagem: str = None):
    if canal_ou_msg and canal_ou_msg.startswith('<#'):
        try:
            target_channel = await commands.TextChannelConverter().convert(ctx, canal_ou_msg)
            msg_final = mensagem
        except:
            target_channel, msg_final = ctx.channel, f"{canal_ou_msg} {mensagem or ''}"
    else:
        target_channel, msg_final = ctx.channel, f"{canal_ou_msg} {mensagem or ''}".strip()
    if not msg_final or msg_final == "None": return await ctx.send("❌ Você precisa digitar uma mensagem!")
    try: await ctx.message.delete()
    except: pass
    await target_channel.send(msg_final)
    await enviar_log(ctx, f"📢 **Comando !say**\n**Canal:** {target_channel.mention}\n**Conteúdo:** {msg_final}", 0x9b59b6)

@bot.command()
@eh_staff()
async def denunciar(ctx, membro: discord.Member, *, motivo: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO blacklist (user_id, motivo, staff_id) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET motivo = EXCLUDED.motivo', (membro.id, motivo, ctx.author.id))
        conn.commit()
        alterar_rep(membro.id, -999, definir=True)
        embed = discord.Embed(title="🚫 Usuário Banido das Trocas", color=0xff0000)
        embed.add_field(name="Membro", value=membro.mention, inline=True)
        embed.add_field(name="Motivo", value=motivo, inline=True)
        await ctx.send(embed=embed)
        await enviar_log(ctx, f"🚫 **BLACK-LIST**\nAlvo: {membro.mention}\nMotivo: {motivo}", 0xff0000)
    except Exception as e: await ctx.send(f"❌ Erro: {e}")
    finally: conn.close()

@bot.command()
@eh_staff()
async def perdoar(ctx, membro: discord.Member):
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
    await ctx.send("📂 Gerando backup...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, rep FROM usuarios ORDER BY rep DESC')
        usuarios = cursor.fetchall()
        cursor.execute('SELECT user_id, motivo FROM blacklist')
        blacklisted = cursor.fetchall()
        conn.close()
        buffer = io.StringIO()
        buffer.write(f"--- BACKUP ARC RAIDERS BRASIL ({datetime.now().strftime('%d/%m/%Y %H:%M')}) ---\n\n🌟 RANKING:\n")
        for uid, pts in usuarios:
            u = bot.get_user(uid)
            buffer.write(f"ID: {uid} | Nome: {u.name if u else 'Desconhecido'} | Pts: {pts}\n")
        buffer.write("\n🚫 BLACKLIST:\n")
        for uid, mot in blacklisted:
            u = bot.get_user(uid)
            buffer.write(f"ID: {uid} | Nome: {u.name if u else 'Desconhecido'} | Motivo: {mot}\n")
        buffer.seek(0)
        await ctx.send(content="✅ Backup concluído:", file=discord.File(fp=buffer, filename=f"backup_{datetime.now().strftime('%d_%m_%Y')}.txt"))
    except Exception as e: await ctx.send(f"❌ Erro: {e}")

# --- EVENTOS ---
@bot.event
async def on_ready():
    setup_db()
    bot.add_view(FinalizarTrocaView()) # Essencial para o botão funcionar após reiniciar
    if not manter_banco_vivo.is_running():
        manter_banco_vivo.start()
    print(f"✅ {bot.user.name} ONLINE!")
    await bot.change_presence(activity=discord.Game(name="!ajuda | ARC Raiders Brasil"))

@bot.event
async def on_thread_create(thread):
    await asyncio.sleep(2)
    # 1. Checa Blacklist
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT motivo FROM blacklist WHERE user_id = %s', (thread.owner_id,))
    blacklisted = cursor.fetchone()
    conn.close()

    if blacklisted:
        await thread.send(f"🚨 **ALERTA DE SEGURANÇA** 🚨\n{thread.owner.mention}, você está na **LISTA NEGRA** e não pode trocar.\n**Motivo:** {blacklisted[0]}")
        await thread.edit(locked=True, archived=True)
        return

    # 2. Envia Boas-vindas e Botão se for no fórum de trocas
    if thread.parent_id == ID_FORUM_TROCA:
        try:
            embed = discord.Embed(
                title="📦 Nova Troca Iniciada!",
                description=(
                    f"Olá {thread.owner.mention}, bem-vindo ao sistema de trocas!\n\n"
                    "**Dicas de Segurança:**\n"
                    "1. Verifique a reputação de alguém usando o comando `!perfil @membro` antes fazer uma troca.\n"
                    "2. Use o comando `!rep @membro` apenas após a troca ser concluída com sucesso.\n"
                    "3. Se por acaso for scammado, abra um ticket acionando nossos mods imediatamente e use o comando `!neg @membro` para negativar o raider.\n\n"
                    "***RMT: Compra e venda de itens com dinheiro real é PROIBIDO e passivo de banimento aqui e no jogo, cuida.***\n\n"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="ARC Raiders Brasil - Sistema de Trocas e Reputação")
            await thread.send(embed=embed, view=FinalizarTrocaView())
            print(f"✅ Botão enviado no tópico: {thread.name}")
        except Exception as e: print(f"❌ Erro thread: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Aguarde {int(error.retry_after // 60)} minutos.", delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        if not ctx.author.guild_permissions.administrator:
             await ctx.send(f"❌ {ctx.author.mention}, este comando não pode ser usado aqui.", delete_after=7)

@tasks.loop(minutes=10)
async def manter_banco_vivo():
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()
            print("ping no banco: OK")
    except Exception as e: print(f"Erro ping banco: {e}")

if __name__ == "__main__":
    setup_db()
    bot.run(TOKEN)