"""Erros de domínio.

Camada pura: não importa nada do projeto nem de biblioteca de I/O. As camadas
de cima traduzem estes erros em resposta HTTP.
"""


class ErroDominio(Exception):
    """Raiz de todos os erros previstos da aplicação.

    `mensagem` é escrita para o usuário final: diz o que aconteceu e o que
    fazer, sem jargão e sem pedir desculpas.
    """

    codigo = "erro_interno"
    status_http = 500

    def __init__(self, mensagem: str, detalhe: str | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.detalhe = detalhe


class RecursoNaoEncontrado(ErroDominio):
    codigo = "nao_encontrado"
    status_http = 404


class EntradaInvalida(ErroDominio):
    codigo = "entrada_invalida"
    status_http = 422


class LimiteExcedido(ErroDominio):
    """Consulta acima do teto de bytes, ou sessão acima do teto de planos."""

    codigo = "limite_excedido"
    status_http = 429


class ServicoIndisponivel(ErroDominio):
    """Falha ao falar com BigQuery ou Gemini."""

    codigo = "servico_indisponivel"
    status_http = 503


class CatalogoInvalido(ErroDominio):
    """Um YAML do catálogo não passou na validação.

    É erro de startup, não de requisição: o serviço não sobe com catálogo
    quebrado. Ignorar em silêncio faria a tabela sumir do índice e a aplicação
    passaria a responder "não tenho cobertura para isso" sem motivo aparente.
    """

    codigo = "catalogo_invalido"
    status_http = 500
