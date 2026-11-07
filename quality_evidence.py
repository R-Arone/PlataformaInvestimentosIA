"""Checklist evidence is not a probability of safety or financial return."""


def summarize(study):
    checks=[c for g in study.get('groups',[]) if g.get('key')!='price' for c in g.get('checks',[]) if c.get('status')!='na' and c.get('scope')!='price']
    counts={s:sum(c.get('status')==s for c in checks) for s in ('pass','fail','unknown')}
    total=sum(counts.values());known=counts['pass']+counts['fail'];coverage=100*known/total if total else 0
    return dict(**counts,total=total,known=known,coverage=round(coverage,2),documented_score=round(100*counts['pass']/total,2) if total else None,
        observed_score=round(100*counts['pass']/known,2) if known else None,
        status='insufficient' if coverage<50 else 'partial' if coverage<80 else 'broad',
        label='Análise inconclusiva' if coverage<50 else 'Cobertura parcial' if coverage<80 else 'Cobertura ampla',
        note='Atendidos, reprovados e sem dados são estados distintos. A nota mede critérios comprovados, não segurança, probabilidade de alta ou ausência de risco.')
