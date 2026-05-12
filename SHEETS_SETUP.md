# Integração com Google Sheets — Eloana Velluto

## Passo a passo

### 1. Criar a planilha
1. Acesse [Google Sheets](https://sheets.google.com) e crie uma nova planilha
2. Renomeie as abas (guias) para exatamente:
   - `Produtos`
   - `Vendas`
   - `Dívidas`

### 2. Criar o Apps Script
1. Na planilha, clique em **Extensões → Apps Script**
2. Apague todo o código existente e cole o seguinte:

```javascript
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet;

    if (data.tipo === 'produto') {
      sheet = ss.getSheetByName('Produtos');
      if (sheet.getLastRow() === 0) {
        sheet.appendRow(['ID', 'Nome', 'Preço', 'Custo', 'Cor', 'Variação', 'Tamanhos', 'Data']);
      }
      sheet.appendRow([
        data.id, data.nome, data.preco, data.precoCusto || 0,
        data.cor || '', data.variacaoTipo || 'tamanho',
        JSON.stringify(data.tamanhos), new Date().toLocaleString('pt-BR')
      ]);

    } else if (data.tipo === 'venda') {
      sheet = ss.getSheetByName('Vendas');
      if (sheet.getLastRow() === 0) {
        sheet.appendRow(['ID', 'Produto', 'Tamanho', 'Qtd', 'Valor Unit.', 'Total', 'Pagamento', 'Data']);
      }
      sheet.appendRow([
        data.id, data.produtoNome, data.tamanho || '', data.quantidade,
        data.valorUnitario, data.valorTotal, data.pagamento, data.data
      ]);

    } else if (data.tipo === 'divida') {
      sheet = ss.getSheetByName('Dívidas');
      if (sheet.getLastRow() === 0) {
        sheet.appendRow(['ID', 'Nome', 'Tipo', 'Valor Total', 'Parcelas', 'Data']);
      }
      sheet.appendRow([
        data.id, data.nome, data.tipo, data.valorTotal,
        data.parcelas ? data.parcelas.length : 1, new Date().toLocaleString('pt-BR')
      ]);

    } else if (data.tipo === 'lancamento') {
      sheet = ss.getSheetByName('Lançamentos') || ss.insertSheet('Lançamentos');
      if (sheet.getLastRow() === 0) {
        sheet.appendRow(['ID', 'Tipo', 'Descrição', 'Valor', 'Data', 'Categoria']);
      }
      sheet.appendRow([
        data.id, data.tipoLanc, data.descricao, data.valor, data.data, data.categoria || ''
      ]);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ status: 'error', message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
```

3. Clique em **Salvar** (ícone de disquete)

### 3. Publicar o Apps Script como Web App
1. Clique em **Implantar → Nova implantação**
2. Tipo: **Aplicativo web**
3. Executar como: **Eu** (sua conta Google)
4. Quem tem acesso: **Qualquer pessoa**
5. Clique em **Implantar**
6. Copie a URL gerada (começa com `https://script.google.com/macros/s/...`)

### 4. Configurar no sistema
1. Abra o arquivo `index.html` em um editor de texto
2. Localize a linha (próxima ao início do JavaScript):
   ```javascript
   const SHEETS_WEBHOOK_URL = "COLE_AQUI_A_URL_DO_APPS_SCRIPT";
   ```
3. Substitua `COLE_AQUI_A_URL_DO_APPS_SCRIPT` pela URL copiada no passo anterior

### 5. Verificar
- Cadastre um produto no app
- Abra a planilha Google Sheets e veja se a linha apareceu na aba **Produtos**

## Observações
- A sincronização é **silenciosa**: se falhar, o app continua funcionando normalmente com localStorage
- Dados antigos (antes da configuração) não são enviados automaticamente — apenas novos registros
- Para reenviar dados existentes, use o botão **Backup** para exportar o JSON e importe manualmente na planilha
- A URL do Apps Script deve ser **reimplantada** se você fizer alterações no código
