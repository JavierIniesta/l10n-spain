# -*- encoding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2008 ACYSOS S.L. (http://acysos.com) All Rights Reserved.
#                    Pedro Tarrafeta <pedro@acysos.com>
#
# WARNING: This program as such is intended to be used by professional
# programmers who take the whole responsability of assessing all potential
# consequences resulting from its eventual inadequacies and bugs
# End users who are looking for a ready-to-use solution with commercial
# garantees and support are strongly adviced to contract a Free Software
# Service Company
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
##############################################################################

import wizard
import osv
import pooler
import threading
import netsvc

_transaction_form = '''<?xml version="1.0"?>
<form string="Cierre de Ejercicio">
	<field name="ejercicio_cierre_id"/>
	<field name="periodo_cierre_id" />
	<field name="ejercicio_apertura_id"/>
	<field name="periodo_apertura_id" />
	<newline/>
	<separator string="Asiento de Perdidas y Ganancias" colspan="4"/>
	<field name="asiento_pyg"/>
	<field name="cuenta_pyg" />
	<field name="texto_pyg" colspan="3"/>
	<field name="diario_pyg" />
	<newline/>
	<separator string="Asientos de Cierre y Apertura" colspan="4"/>
	<field name="nombre_asiento_apertura" colspan="3"/>
	<field name="nombre_asiento" colspan="3"/>
	<field name="diario_cierre" colspan="3"/>
	<separator string="CONFIRMAR CIERRE" colspan="4"/>
	<field name="sure"/>
</form>'''

_transaction_fields = {
	'ejercicio_cierre_id': {'string':'Ejercicio a cerrar', 'type':'many2one', 'relation': 'account.fiscalyear','required':True, 'domain':[('state','=','draft')]},
	'periodo_cierre_id': {'string': 'Periodo Cierre', 'type': 'many2one', 'relation':'account.period', 'required': True, 'domain':[('state','=','draft')]},
	'ejercicio_apertura_id': {'string':'Ejercicio apertura', 'type':'many2one', 'relation': 'account.fiscalyear', 'domain':[('state','=','draft')], 'required':True},
	'periodo_apertura_id': {'string': 'Periodo Apertura', 'type': 'many2one', 'relation':'account.period', 'required': True, 'domain':[('state','=','draft')]},
	'asiento_pyg': {'string':'Crear Asiento de Pérdidas y Ganancias', 'type':'boolean', 'required':True, 'default': lambda *a:True},
	'cuenta_pyg': {'string': 'Cuenta de Pérdidas y Ganancias', 'type':'many2one', 'relation':'account.account', 'domain':[('code','ilike','129'),('type','=','equity')], 'required':True},
	'texto_pyg': {'string':'Descripción asiento reg.PyG', 'type':'char', 'size': 64, 'required':True},
	'diario_pyg': {'string':'Diario Regularización PyG', 'type':'many2one', 'relation': 'account.journal', 'required':True},
	'nombre_asiento_apertura': {'string':'Descripción asiento apertura', 'type':'char', 'size': 64, 'required':True},
	'nombre_asiento': {'string':'Descripción asiento cierre', 'type':'char', 'size': 64, 'required':True},
	'diario_cierre': {'string':'Diario Apertura', 'type':'many2one', 'relation': 'account.journal', 'required':True},
	'sure': {'string':'Marque la casilla si está seguro', 'type':'boolean'},
}

def _data_load(self, cr, uid, data, context):
	data['form']['asiento_pyg'] = True
	data['form']['texto_pyg'] = 'Asiento Reg. Perdidas y Ganancias'
	data['form']['nombre_asiento'] = 'Asiento de Cierre'
	data['form']['nombre_asiento_apertura'] = 'Asiento de Apertura'
	return data['form']


def _data_save(self, cr, uid, data, context):
	if not data['form']['sure']:
		raise wizard.except_wizard('UserError', 'Si está seguro de que quiere cerrar el ejercicio marque la casilla correspondiente')
	if data['form']['asiento_pyg']:
		_asiento_pyg(self, cr, uid, data, context)
	_procedure_cierre(self, cr, uid, data, context)
	return {}


def _asiento_pyg(self, cr, uid, data, context):
	pool = pooler.get_pool(cr.dbname)
	ejercicio_cierre_id = data['form']['ejercicio_cierre_id']
	periodo = pool.get('account.period').browse(cr, uid, data['form']['periodo_cierre_id'])
	cr.execute("select id from account_account WHERE type in ('expense','income')")
	ids = map(lambda x: x[0], cr.fetchall())
	saldo_pyg = 0.0
	context['fiscalyear'] = ejercicio_cierre_id
	apuntes = []
	for account in pool.get('account.account').browse(cr, uid, ids, context):
		if abs(account.balance)>0.0001:
			saldo_pyg += account.balance
			linea =  {
				'debit': account.balance<0 and -account.balance,
				'credit': account.balance>0 and account.balance,
				'name': data['form']['texto_pyg'],
				'date': periodo.date_stop,
				'journal_id': data['form']['diario_pyg'],
				'period_id': periodo.id,
				'account_id': account.id
				}
			apuntes.append((0,0,linea))
	movimiento = {
		'debit': (saldo_pyg >=0 ) and saldo_pyg or 0.0,
		'credit': (saldo_pyg <0 ) and -saldo_pyg or 0.0,
		'name': 'Resultado del ejercicio',
		'date': periodo.date_stop,
		'journal_id': data['form']['diario_pyg'],
		'period_id': periodo.id,
		'account_id': data['form']['cuenta_pyg'],
	}
	apuntes.append((0,0,movimiento))
	asiento = {'name': data['form']['texto_pyg'], 'line_id': apuntes, 'journal_id': data['form']['diario_pyg'], 'period_id': periodo.id,} #'date':periodo.date_stop
	asiento_id = pool.get('account.move').create(cr,uid,asiento)
	pool.get('account.move').button_validate(cr, uid, [asiento_id], context)
	return {}


def revert_move(cr, uid, data, move_id, journal_id, period_id, date, reconcile=True, context={}):
	pool = pooler.get_pool(cr.dbname)
	move = pool.get('account.move').browse(cr, uid, move_id)
	move.write(cr, uid, [move.id], {'state':'draft'})
	copy_id = pool.get('account.move').copy(cr, uid, move.id, {}, context)
	name = data['form']['nombre_asiento_apertura']
	move.write(cr, uid, [copy_id], {'journal_id': journal_id, 'period_id': period_id, 'name':name})
	copy_move = pool.get('account.move').browse(cr, uid, copy_id)
	for line in copy_move.line_id:
		if date:
			line.write(cr, uid, [line.id],{'date': date, 'credit': line.debit, 'debit': line.credit, 'period_id': period_id}, check=False)
		else:
			line.write(cr, uid, [line.id],{'credit': line.debit, 'debit': line.credit, 'period_id': period_id}, check=False)
	if reconcile:
		reconcile_lines = pool.get('account.move.line').search(cr, uid, [('account_id.reconcile','=','True'),('move_id','in',[move.id, copy_id])])
		r_id = pool.get('account.move.reconcile').create(cr, uid, {
			'type': 'manual',
			'line_id': map(lambda x: (4,x,False), reconcile_lines)})
	print "Revertido desde revert"
	return copy_id


def _asiento_cierre(self, db_name, uid, data, context):
	db, pool = pooler.get_db_and_pool(db_name)
	cr = db.cursor()
	ejercicio_cierre_id = data['form']['ejercicio_cierre_id']
	apuntes = []
	periodo = pool.get('account.period').browse(cr, uid, data['form']['periodo_cierre_id'])
	cr.execute("select id from account_account WHERE type not in ('expense','income','view') ORDER BY code")
	ids = map(lambda x: x[0], cr.fetchall())
	context['fiscalyear'] = ejercicio_cierre_id
	saldo_asiento = 0.0
	for account in pool.get('account.account').browse(cr, uid, ids, context):
		if account.close_method=='none' or account.type == 'view':
			continue
		if account.close_method=='balance' or account.close_method == 'unreconciled':
			if abs(account.balance)>0.0001:
				linea = {
					'credit': account.balance>0 and account.balance,
					'debit': account.balance<0 and -account.balance,
					'name': account.name,
					'date': periodo.date_stop,
					'journal_id': data['form']['diario_cierre'],
					'period_id': periodo.id,
					'account_id': account.id
				}
				saldo_asiento += account.balance
				apuntes.append((0,0,linea))
		if account.close_method=='detail':
			offset = 0
			limit = 100
			while True:
				cr.execute('select name,quantity,debit,credit,account_id,ref,amount_currency,currency_id,blocked,partner_id,date_maturity,date_created from account_move_line where account_id=%d and period_id in (select id from account_period where fiscalyear_id=%d) order by id limit %d offset %d', (account.id,ejercicio_cierre_id, limit, offset))
				result = cr.dictfetchall()
				if not result:
					break
				for linea in result:
					linea.update({
						'date': periodo.date_stop,
						'journal_id': data['form']['diario_cierre'],
						'period_id': periodo.id,
					})
					saldo_asiento += linea['debit'] - linea['credit']
					apuntes.append((0,0,linea))
				offset += limit
	print saldo_asiento
	movimiento = {
		'debit': (saldo_asiento >=0 ) and saldo_asiento or 0.0,
		'credit': (saldo_asiento <0 ) and -saldo_asiento or 0.0,
		'name': 'Resultado del ejercicio',
		'date': periodo.date_stop,
		'journal_id': data['form']['diario_cierre'],
		'period_id': periodo.id,
		'account_id': data['form']['cuenta_pyg'],
	}
	apuntes.append((0,0,movimiento))
	asiento = {'name': data['form']['nombre_asiento'], 'line_id': apuntes, 'journal_id': data['form']['diario_cierre'], 'period_id': periodo.id,} #'date':periodo.date_stop
	asiento_id = pool.get('account.move').create(cr,uid,asiento)
	print "Asiento cierre id:" + str(asiento_id)

	apertura_id = revert_move(cr, uid, data, asiento_id, data['form']['diario_cierre'], data['form']['periodo_apertura_id'], pool.get('account.period').browse(cr,uid,data['form']['periodo_apertura_id']).date_start, True, context)
	print "Asiento apertura id:" + str(apertura_id)
	#pool.get('account.move').button_validate(cr,uid,[asiento_id, apertura_id],context)

	result = cr.commit()
	return {}


def _procedure_cierre(self, cr, uid, data, context):
	threaded_calculation = threading.Thread(target=_asiento_cierre, args=(self, cr.dbname, uid, data, context))
	threaded_calculation.start()
	return {}


class wiz_journal_close(wizard.interface):
	states = {
		'init': {
			'actions': [_data_load],
			'result': {'type': 'form', 'arch':_transaction_form, 'fields':_transaction_fields, 'state':[('end','Cancelar'),('close','Cerrar ejercicio fiscal')]}
		},
		'close': {
			'actions': [_data_save],
			'result': {'type': 'state', 'state':'end'}
		}
	}
wiz_journal_close('l10n_chart_ES.fiscalyear.close')

