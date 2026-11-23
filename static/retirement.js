'use strict';

const retirementMaxYears = 100;
const retirementModes = [
  ['income', 'Em X anos, quanto posso sacar por mês?'],
  ['date', 'Quando posso começar a sacar sem prazo para terminar?'],
  ['duration', 'Por quanto tempo o meu dinheiro dura?'],
];
const retirementFrequencies = [['1', 'Mensal'], ['3', 'Trimestral'], ['6', 'Semestral'], ['12', 'Anual']];
const retirementIndexing = [['indexed', 'Corrigidos pela inflação'], ['fixed', 'Fixos em reais nominais']];
const retirementReturns = [
  ['gross', 'Bruta, antes de custos e impostos'],
  ['net', 'Líquida nominal, sem descontar a inflação'],
  ['real', 'Líquida real, já descontada a inflação'],
];
const retirementFields = {
  principal: ['Patrimônio inicial (R$)', 300000, 0, 1e12],
  contribution: ['Aporte por período até parar (R$ de hoje)', 3000, 0, 1e12],
  years: ['Anos até começar a sacar', 25, 0, retirementMaxYears, true],
  goal: ['Meta de patrimônio (R$ de hoje)', 1000000, 0, 1e12],
  annualReturn: ['Rentabilidade anual (%)', 9, -50, 100],
  annualDrag: ['Custos e impostos estimados (p.p. ao ano)', 1.5, 0, 50],
  inflation: ['Inflação média (% ao ano)', 4.5, -50, 50],
  withdrawal: ['Saque mensal desejado (R$ de hoje)', 12000, 0, 1e12],
  postContribution: ['Aporte mensal após começar a sacar (R$ de hoje)', 0, 0, 1e12],
  withdrawalYears: ['Anos de retiradas no gráfico', 35, 1, retirementMaxYears, true],
};

function retirementUsesField(key, mode, returnBasis) {
  if (key === 'years') return mode !== 'date';
  if (key === 'withdrawal') return mode !== 'income';
  if (key === 'goal' || key === 'withdrawalYears') return mode === 'duration';
  if (key === 'annualDrag') return returnBasis === 'gross';
  return true;
}

function retirementInputs(data) {
  const mode = data.mode ?? 'duration';
  const returnBasis = data.returnBasis ?? 'net';
  const frequency = Number(data.frequency);
  if (!retirementModes.some(([key]) => key === mode) ||
      !retirementReturns.some(([key]) => key === returnBasis) ||
      !retirementFrequencies.some(([key]) => Number(key) === frequency) ||
      !retirementIndexing.some(([key]) => key === data.contributionIndexing) ||
      !retirementIndexing.some(([key]) => key === data.withdrawalIndexing)) {
    throw Error('Confira o tipo de simulação, a rentabilidade e as opções de aportes e saques.');
  }
  const values = {};
  for (const [key, [label, , min, max, integer]] of Object.entries(retirementFields)) {
    if (!retirementUsesField(key, mode, returnBasis)) continue;
    let raw = data[key];
    if (key === 'postContribution' && (raw == null || raw === '')) raw = 0;
    const value = typeof raw === 'number' || (typeof raw === 'string' && raw.trim()) ? Number(raw) : NaN;
    if (!Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) {
      throw Error(`Informe um valor ${integer ? 'inteiro ' : ''}entre ${fmt(min, 0)} e ${fmt(max, 0)} em “${label}”.`);
    }
    values[key] = value;
  }
  if (returnBasis === 'gross' && values.annualReturn - values.annualDrag <= -100) {
    throw Error('A rentabilidade após custos e impostos precisa ser maior que −100% ao ano.');
  }
  return {...values, mode, returnBasis, frequency, contributionIndexing: data.contributionIndexing,
    withdrawalIndexing: data.withdrawalIndexing};
}

function projectRetirement(data) {
  const p = retirementInputs(data);
  const inflationLog = Math.log1p(p.inflation / 100) / 12;
  const inputLog = Math.log1p((p.annualReturn - (p.annualDrag ?? 0)) / 100) / 12;
  const nominalLog = p.returnBasis === 'real' ? inputLog + inflationLog : inputLog;
  const realLog = p.returnBasis === 'real' ? inputLog : inputLog - inflationLog;
  const realFactor = Math.exp(realLog);

  // Fixed payouts share one nominal amount from the first withdrawal month onward.
  const indexed = p.withdrawalIndexing === 'indexed';
  const payoutLog = indexed ? realLog : nominalLog;
  const payoutRate = Math.expm1(payoutLog);
  const toPayment = indexed ? 1 : Math.exp(inflationLog);
  const netWithdrawal = (p.withdrawal ?? 0) - p.postContribution;
  const payment = Math.max(0, netWithdrawal) * toPayment;
  const capitalForPerpetuity = payment === 0 ? 0 : payoutRate > 0 ? payment / payoutRate : null;

  const accumulationLimit = (p.mode === 'date' ? retirementMaxYears : p.years) * 12;
  let accumulationMonths = 0;
  let initialBalance = p.principal;
  let goalMonth = p.mode === 'duration' && initialBalance >= p.goal ? 0 : null;
  const yearlyBalances = [initialBalance];
  const targetReached = () => capitalForPerpetuity !== null && initialBalance >= capitalForPerpetuity;
  while (accumulationMonths < accumulationLimit && (p.mode !== 'date' || !targetReached())) {
    if (p.mode === 'date' && capitalForPerpetuity === null) break;
    accumulationMonths++;
    initialBalance *= realFactor;
    if (accumulationMonths % p.frequency === 0) {
      initialBalance += p.contributionIndexing === 'indexed' ? p.contribution :
        p.contribution * Math.exp(-accumulationMonths * inflationLog);
    }
    if (p.mode === 'duration' && goalMonth === null && initialBalance >= p.goal) goalMonth = accumulationMonths;
    if (p.mode === 'duration' && accumulationMonths % 12 === 0) yearlyBalances.push(initialBalance);
  }

  const maxMonthlyWithdrawal = p.postContribution + initialBalance * Math.max(0, payoutRate) / toPayment;
  let fundedMonths = Infinity;
  if (payment > 0 && !targetReached()) {
    const months = payoutRate === 0 ? initialBalance / payment :
      -Math.log1p(-initialBalance * payoutRate / payment) / payoutLog;
    fundedMonths = Math.floor(months + 1e-8);
  }

  const withdrawalMonths = (p.withdrawalYears ?? 0) * 12;
  const capitalForHorizon = payment * (payoutRate === 0 ? withdrawalMonths :
    -Math.expm1(-withdrawalMonths * payoutLog) / payoutRate);
  let balance = initialBalance;
  for (let month = 1; month <= withdrawalMonths; month++) {
    const withdrawal = indexed ? netWithdrawal : netWithdrawal * Math.exp(-(month - 1) * inflationLog);
    balance = Math.max(0, balance * realFactor - withdrawal);
    if (month % 12 === 0) yearlyBalances.push(balance);
  }

  return {
    parameters: p, initialBalance, accumulationMonths, goalMonth, capitalForHorizon, capitalForPerpetuity,
    earliestMonth: p.mode === 'date' && targetReached() ? accumulationMonths : null,
    maxMonthlyWithdrawal, fundedMonths, yearlyBalances,
    netAnnualReturn: 100 * Math.expm1(12 * nominalLog),
    realAnnualReturn: 100 * Math.expm1(12 * realLog),
    monthlyRealReturn: Math.expm1(realLog), payoutRate, toPayment, payment,
  };
}

function retirementDuration(months) {
  if (months === 0) return '0 meses';
  const years = Math.floor(months / 12);
  const remainder = months % 12;
  return [years ? `${fmt(years, 0)} ${years === 1 ? 'ano' : 'anos'}` : '',
    remainder ? `${remainder} ${remainder === 1 ? 'mês' : 'meses'}` : ''].filter(Boolean).join(' e ');
}

function retirementEquations(r) {
  const p = r.parameters;
  const indexed = p.withdrawalIndexing === 'indexed';
  const monthlyPercent = rate => `${fmt(100 * rate, 4)}%`;
  const inputRate = p.returnBasis === 'gross' ?
    `<p>Taxa líquida nominal = ${pct(p.annualReturn)} brutos − ${fmt(p.annualDrag)} p.p. de custos e impostos = <b>${pct(r.netAnnualReturn)}</b> ao ano.</p>` : '';
  const annualEquation = p.returnBasis === 'real' ?
    '1 + taxa nominal anual = (1 + taxa real anual) × (1 + inflação anual)' :
    '1 + taxa real anual = (1 + taxa nominal anual) / (1 + inflação anual)';
  const capitalRule = r.payment === 0 ?
    'Como o aporte mensal cobre todo o saque, o capital necessário para essa retirada é zero.' :
    'Para uma retirada líquida positiva, o capital por prazo indeterminado é Q / r quando r é positivo. Com r igual a zero ou negativo, nenhum capital finito sustenta esse saque indefinidamente.';
  return `<details class="simple-advanced retirement-equations"><summary>Como o cálculo foi feito</summary>
    <h3>Taxas e inflação</h3>
    ${inputRate}<p>${annualEquation}.</p>
    <p>A taxa mensal equivalente é (1 + taxa anual)<sup>1/12</sup> − 1. O saldo cresce à taxa <b>real de ${monthlyPercent(r.monthlyRealReturn)} ao mês</b>.</p>
    <h3>Patrimônio durante os aportes</h3>
    <p><var>B</var><sub>t</sub> = <var>B</var><sub>t−1</sub> × (1 + taxa real mensal) + <var>A</var><sub>t</sub>.</p>
    <p><var>B</var><sub>t</sub> é o saldo no fim do mês <var>t</var>. <var>A</var><sub>t</sub> é o aporte em reais de hoje, somado no fim do mês conforme a frequência escolhida.
      ${p.contributionIndexing === 'fixed' ? 'Para um aporte fixo em reais nominais, o valor de hoje é o aporte nominal dividido por (1 + inflação mensal) elevado ao número de meses desde hoje.' : 'Nos meses de aporte, o valor tem sempre o mesmo poder de compra.'}</p>
    <h3>Saques e aportes após parar</h3>
    <p><var>S</var> é o saque mensal e <var>C</var> é o aporte mensal após parar, ambos em reais de hoje no primeiro mês dessa fase. A retirada líquida no primeiro mês é <var>S</var> − <var>C</var>.</p>
    <p>${indexed ? 'Com correção pela inflação, essa retirada mantém o poder de compra. Usamos a taxa real mensal para r e o fator de conversão f = 1.' :
    'Com valores fixos em reais nominais, a retirada em reais de hoje nos meses seguintes é dividida por (1 + inflação mensal) a cada mês. Usamos a taxa nominal mensal para r. O fator f = 1 + inflação mensal converte o primeiro saque para a mesma referência nominal do saldo antes do primeiro mês de retirada.'}
      Neste cenário, <var>r</var> = ${monthlyPercent(r.payoutRate)} e <var>f</var> = ${fmt(r.toPayment, 6)}.</p>
    ${p.mode !== 'date' ? `<p>Saque mensal máximo = <var>C</var> + <var>B</var><sub>T</sub> × máx(<var>r</var>, 0) / <var>f</var>, em que <var>B</var><sub>T</sub> é o saldo acumulado antes do primeiro saque. Com os dados escolhidos, <var>C</var> = ${money(p.postContribution)} e <var>B</var><sub>T</sub> = ${money(r.initialBalance)}.</p>` : ''}
    ${p.mode !== 'income' ? `<p>Para calcular o capital necessário, <var>Q</var> = máx(<var>S</var> − <var>C</var>, 0) × <var>f</var>. Neste cenário, <var>Q</var> = ${money(r.payment)}.</p><p>${capitalRule}</p>` : ''}
    ${p.mode === 'date' ? '<p>O prazo é o primeiro mês em que o patrimônio acumulado alcança o capital necessário.</p>' : ''}
    ${p.mode === 'duration' ? `<p>Para <var>n</var> meses de saques, o capital necessário é <var>Q</var> × [1 − (1 + <var>r</var>)<sup>−n</sup>] / <var>r</var>. Quando <var>r</var> é zero, é <var>Q</var> × <var>n</var>.</p>
      <p>A duração corresponde ao maior número de pagamentos completos que o capital acumulado cobre. No gráfico, o saldo de cada mês é o saldo anterior acrescido da rentabilidade real e reduzido pela retirada líquida do mês, com piso de zero.</p>` : ''}
  </details>`;
}

function retirementResults(data) {
  const r = projectRetirement(data);
  const p = r.parameters;
  const indexed = p.withdrawalIndexing === 'indexed';
  const assumptions = `<p>Em reais de hoje. Taxa líquida nominal de <b>${pct(r.netAnnualReturn)} ao ano</b> e taxa líquida real de <b>${pct(r.realAnnualReturn)} ao ano</b> após a inflação.</p>`;
  const payoutNote = indexed ? 'Saque acompanha a inflação.' : 'Valor do primeiro saque, mantido fixo em reais nominais depois.';
  const cashFlowNote = p.postContribution > 0 ? `<p class="form-hint">O aporte de ${money(p.postContribution)} no primeiro mês cobre parte ou todo o saque. A diferença entre o saque e esse aporte é o valor líquido retirado da carteira.</p>` : '';
  const modelNote = '<p class="form-hint">A projeção considera uma taxa constante. Se o rendimento variar de mês para mês, o patrimônio pode durar mais ou menos.</p>';
  const maxWithdrawal = Math.floor(r.maxMonthlyWithdrawal * 100) / 100;
  const maximumCard = card('Saque mensal máximo por prazo indeterminado', money(maxWithdrawal), payoutNote, 'feature');
  const balanceCard = card('Saldo ao começar a sacar', money(r.initialBalance),
    r.accumulationMonths ? `Após ${retirementDuration(r.accumulationMonths)}` : 'Se começar hoje');

  if (p.mode === 'income') return `<h2>Quanto posso sacar por mês?</h2>${assumptions}
    <div class="cards">${maximumCard}${balanceCard}</div>${cashFlowNote}${modelNote}${retirementEquations(r)}`;

  if (p.mode === 'date') {
    const earliest = r.earliestMonth === null ? 'Meta não atingida' : r.earliestMonth === 0 ? 'Hoje' : retirementDuration(r.earliestMonth);
    const reason = r.capitalForPerpetuity === null ?
      'O rendimento considerado não sustenta saques líquidos positivos por prazo indeterminado.' :
      `Com esses aportes, o saldo não alcança o capital necessário em até ${retirementMaxYears} anos.`;
    return `<h2>Quando posso começar a sacar?</h2>${assumptions}
      <div class="cards">
        ${card('Tempo até poder começar', earliest, r.earliestMonth === null ? reason : `Para sacar ${money(p.withdrawal)} por mês. ${payoutNote}`, 'feature')}
        ${card('Capital para sacar por prazo indeterminado', r.capitalForPerpetuity === null ? 'Sem valor finito' : money(r.capitalForPerpetuity), 'Patrimônio necessário ao iniciar a fase de retiradas')}
        ${r.earliestMonth === null ? '' : balanceCard}
      </div>${cashFlowNote}${modelNote}${retirementEquations(r)}`;
  }

  const duration = p.withdrawal === 0 ? 'Sem retiradas' : r.fundedMonths === Infinity ? 'Indefinidamente' : retirementDuration(r.fundedMonths);
  const rows = r.yearlyBalances.map((balance, year) => `<tr><th scope="row">${year}</th><td>${year === 0 ? 'Hoje' : year === p.years ? 'Início dos saques' : year < p.years ? 'Aportes' : 'Retiradas'}</td><td>${money(balance)}</td></tr>`).join('');
  return `<h2>Por quanto tempo o dinheiro dura?</h2>${assumptions}
    <div class="cards">
      ${maximumCard}${balanceCard}
      ${card('Duração dos saques', duration, 'Meses em que o saque desejado pode ser pago integralmente')}
      ${card('Prazo até a meta de patrimônio', r.goalMonth === null ? 'Fora do prazo' : r.goalMonth === 0 ? 'Já atingida' : retirementDuration(r.goalMonth), 'Primeiro mês em que o saldo alcança a meta antes dos saques')}
      ${card(`Capital para ${p.withdrawalYears} ${p.withdrawalYears === 1 ? 'ano' : 'anos'} de saques`, money(r.capitalForHorizon), 'Patrimônio necessário ao iniciar a fase de retiradas')}
      ${card('Capital para sacar por prazo indeterminado', r.capitalForPerpetuity === null ? 'Sem valor finito' : money(r.capitalForPerpetuity), payoutNote)}
    </div>${cashFlowNote}${modelNote}
    <h3>Evolução do patrimônio</h3>
    ${lineChart(r.yearlyBalances, 'Patrimônio em reais de hoje desde o início da simulação')}
    <p class="form-hint">Do ano 0 ao ano ${p.years + p.withdrawalYears}. Os saques começam após o ano ${p.years}.</p>
    <details><summary>Ver saldos por ano</summary><div class="table-wrap"><table><thead><tr><th>Ano</th><th>Etapa</th><th>Saldo em reais de hoje</th></tr></thead><tbody>${rows}</tbody></table></div></details>
    ${retirementEquations(r)}`;
}

function retirementView() {
  const input = key => {
    const [label, value, min, max, integer] = retirementFields[key];
    const required = key === 'postContribution' ? '' : 'required';
    return field(key, label, value, 'number', `${required} min="${min}" max="${max}" step="${integer ? 1 : 'any'}" inputmode="${integer ? 'numeric' : 'decimal'}"`);
  };
  return page('Simulador de aposentadoria', 'Escolha o que quer descobrir e ajuste os valores do seu cenário.') + `
    <section class="panel"><form id="retirement-form" autocomplete="off">
      ${select('mode', 'O que você quer simular?', retirementModes, 'income')}
      <h2>Patrimônio e aportes</h2>
      <div class="form-grid">${input('principal')}${input('contribution')}${input('years')}${input('withdrawal')}</div>
      ${button('retirement-use-portfolio', 'Usar o saldo da minha carteira')}
      <p class="form-hint" id="retirement-years-hint">Informe 0 anos para simular saques a partir de hoje.</p>
      <h2>Rentabilidade e inflação</h2>
      <div class="form-grid">
        ${select('returnBasis', 'Tipo de rentabilidade', retirementReturns, 'gross')}
        ${input('annualReturn')}${input('annualDrag')}${input('inflation')}
      </div>
      <p class="form-hint">Os números iniciais são exemplos editáveis. Na opção bruta, o desconto em pontos percentuais é aplicado à taxa anual antes do ajuste pela inflação.</p>
      <details class="simple-advanced"><summary>Frequência, correção e aportes após parar</summary>
        <div class="form-grid">
          ${select('frequency', 'Frequência dos aportes até parar', retirementFrequencies, '1')}
          ${select('contributionIndexing', 'Correção dos aportes até parar', retirementIndexing, 'indexed')}
          ${input('postContribution')}
          ${select('withdrawalIndexing', 'Correção dos saques e aportes após parar', retirementIndexing, 'indexed')}
        </div>
        <p class="form-hint">O aporte mensal após parar é opcional e começa no mesmo mês do primeiro saque. Ele continua durante todo o período simulado. Os fluxos ocorrem no fim de cada mês.</p>
      </details>
      <details class="simple-advanced" id="retirement-timeline-options"><summary>Meta de patrimônio e período do gráfico</summary>
        <div class="form-grid">${input('goal')}${input('withdrawalYears')}</div>
      </details>
      <div class="form-error" role="alert"></div><button class="button" type="submit" aria-controls="retirement-result">Simular aposentadoria</button>
    </form></section><section class="panel" id="retirement-result" tabindex="-1" aria-label="Resultado da simulação" hidden></section>`;
}

function bindRetirement() {
  const form = $('#retirement-form');
  if (!form || form.dataset.bound) return;
  const results = $('#retirement-result');
  const applyOptions = () => {
    const mode = form.elements.mode.value;
    const returnBasis = form.elements.returnBasis.value;
    for (const key of Object.keys(retirementFields)) {
      const control = form.elements[key];
      control.disabled = !retirementUsesField(key, mode, returnBasis);
      control.closest('.field').hidden = control.disabled;
    }
    $('#retirement-years-hint', form).hidden = mode === 'date';
    $('#retirement-timeline-options', form).hidden = mode !== 'duration';
    results.hidden = true;
  };
  applyOptions();
  form.addEventListener('change', event => {
    if (event.target.name === 'mode' || event.target.name === 'returnBasis') applyOptions();
  });
  form.addEventListener('input', () => { results.hidden = true; });
  $('[data-action=retirement-use-portfolio]', form).addEventListener('click', () => {
    form.elements.principal.value = Math.max(0, totals().total).toFixed(2);
    results.hidden = true;
    form.elements.principal.focus();
  });
  wireForm('#retirement-form', data => {
    results.innerHTML = retirementResults(data);
    results.hidden = false;
    results.focus();
  });
}
