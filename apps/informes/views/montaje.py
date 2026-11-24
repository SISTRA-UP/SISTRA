"""Vistas de montaje de informe (SISTRA-06).

Permite al estudiante registrar su informe de Trabajo Social,
guardarlo como borrador y enviarlo a revisión.

Preparado para integrarse con SISTRA-07 (Aprobación de informe).
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.informes.forms.montaje import (
    InformeForm,
    MSG_06_01,
    MSG_06_02,
    MSG_06_03,
    MSG_06_04,
    MSG_06_05,
    MINIMO_CARACTERES,
)
from apps.informes.models import Informe
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.permisos import requiere_permiso
# Importar las constantes desde el módulo de aprobacion (SISTRA-02)
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, RESULTADO_BLOQUEADO


ESTADOS_EDITABLES = [
    EstadoTramite.BORRADOR,
    EstadoTramite.REQUIERE_MODIFICACION,
]

ESTADOS_BLOQUEADOS = [
    EstadoTramite.EN_REVISION,
    EstadoTramite.APROBADO,
    EstadoTramite.SUBIDO_EN_UP,
    EstadoTramite.APROBADO_EN_UP,
]


def _calcular_avance(informe):
    """Calcula el % de avance. Un campo cuenta como lleno si tiene >= 50 caracteres."""
    campos = ['resultados', 'conclusiones', 'recomendaciones']
    llenos = 0
    for campo in campos:
        if isinstance(informe, dict):
            valor = informe.get(campo, '') or ''
        else:
            valor = getattr(informe, campo, '') or ''
        if len(valor.strip()) >= MINIMO_CARACTERES:
            llenos += 1
    return int((llenos / len(campos)) * 100)


def _registrar_auditoria(usuario, informe, accion, resultado, detalle):
    """Registra una acción en la tabla de auditoría."""
    Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tabla_afectada='informe',
        id_registro_afectado=informe.pk,  # CORREGIDO: usar pk en lugar de id
        detalle=detalle,
        resultado=resultado,
        fecha_hora=timezone.now(),
    )


def _obtener_o_crear_informe(usuario, propuesta):
    """
    Obtiene el informe activo o crea uno nuevo de forma segura.
    Usa transaction.atomic() y select_for_update() para evitar race conditions.
    """
    # Verificar si ya existe un informe activo
    informe = Informe.objects.filter(
        propuesta=propuesta,
        archivado=False,
    ).exclude(estado=EstadoTramite.RECHAZADO).first()
    
    if informe:
        return informe, False  # (informe, fue_creado)
    
    # No existe, crear uno nuevo con bloqueo
    try:
        with transaction.atomic():
            # Bloquear la propuesta para evitar que dos POST simultáneos creen dos informes
            Propuesta.objects.select_for_update().get(pk=propuesta.pk)  # CORREGIDO
            
            # Verificar DE NUEVO que no exista (por si otro POST lo creó mientras esperábamos)
            informe = Informe.objects.filter(
                propuesta=propuesta,
                archivado=False,
            ).exclude(estado=EstadoTramite.RECHAZADO).first()
            
            if informe:
                return informe, False  # Ya existía
            
            # Crear nuevo informe
            n = Informe.objects.filter(propuesta=propuesta).count() + 1
            nuevo_codigo = f'INF-{propuesta.codigo.replace("PROP-", "")}-{n}'
            informe = Informe.objects.create(
                propuesta=propuesta,
                periodo_academico=propuesta.periodo_academico,
                codigo=nuevo_codigo,
                estado=EstadoTramite.BORRADOR,
            )
            
            _registrar_auditoria(
                usuario,
                informe,
                'Crear informe',
                RESULTADO_EXITO,
                f'Código: {informe.codigo} | Versión: {informe.version_entrega}',
            )
            
            return informe, True  # (informe, fue_creado)
            
    except IntegrityError:
        # Si hubo conflicto, buscar el informe que ya existe
        informe = Informe.objects.filter(
            propuesta=propuesta,
            archivado=False,
        ).exclude(estado=EstadoTramite.RECHAZADO).first()
        
        if informe:
            return informe, False
        else:
            raise


@requiere_permiso('informe.montar')
def inicio(request):
    """Vista principal de montaje de informe."""
    usuario = request.user

    # --- Validación: debe ser estudiante (403 si no lo es) ---
    from apps.personas.models import Estudiante
    try:
        estudiante = Estudiante.objects.get(usuario=usuario)
    except Estudiante.DoesNotExist:
        raise PermissionDenied(
            'Solo los estudiantes pueden montar informes.'
        )

    # --- Validación: debe tener propuesta APROBADO EN UP ---
    propuesta = Propuesta.objects.filter(
        proceso__estudiante_carrera__estudiante=estudiante,
        estado=EstadoTramite.APROBADO_EN_UP,
        archivada=False,
    ).first()

    if not propuesta:
        return render(request, 'informes/montaje/inicio.html', {
            'sin_acceso': True,
            'mensaje_error': MSG_06_05,
        })

    # --- Manejo de POST ---
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # Si la acción es "crear_informe", crear el informe
        if accion == 'crear_informe':
            try:
                informe, fue_creado = _obtener_o_crear_informe(usuario, propuesta)
                
                if fue_creado:
                    messages.success(request, 'Informe creado exitosamente. Ahora puedes diligenciarlo.')
                else:
                    messages.info(request, 'El informe ya existía.')
                
                return redirect('informes:montaje')
            except Exception:
                messages.error(request, 'Ocurrió un error al crear el informe. Intenta de nuevo.')
                return redirect('informes:montaje')
        
        # Para otras acciones (guardar_borrador, enviar), debe existir el informe
        informe = Informe.objects.filter(
            propuesta=propuesta,
            archivado=False,
        ).exclude(estado=EstadoTramite.RECHAZADO).first()
        
        if not informe:
            messages.error(request, 'No existe un informe activo. Primero debes crear uno.')
            return redirect('informes:montaje')
        
        # CRÍTICO: Validar bloqueo en el servidor
        if informe.estado not in ESTADOS_EDITABLES:
            messages.error(request, MSG_06_04)
            _registrar_auditoria(
                usuario,
                informe,
                'Editar informe',
                RESULTADO_BLOQUEADO,
                f'Intento de edición en estado: {informe.estado}',
            )
            return redirect('informes:montaje')

        estado_anterior = informe.estado
        form = InformeForm(request.POST, instance=informe, accion=accion)

        if form.is_valid():
            if accion == 'guardar_borrador':
                # NO cambia el estado. Solo guarda los textos.
                informe = form.save()

                _registrar_auditoria(
                    usuario,
                    informe,
                    'Guardar borrador',
                    RESULTADO_EXITO,
                    f'Código: {informe.codigo} | Versión: {informe.version_entrega}',
                )

                messages.success(request, MSG_06_01)
                return redirect('informes:montaje')

            elif accion == 'enviar':
                avance_post = _calcular_avance(form.cleaned_data)

                # CORREGIDO: Si no cumple el avance, NO redirigimos. 
                # Dejamos que el código continúe hasta el render final para devolver 200 y mostrar el error en el formulario.
                if avance_post < 100:
                    messages.error(request, MSG_06_03)
                else:
                    try:
                        with transaction.atomic():
                            # Bloquear el informe para evitar doble envío
                            informe_bloqueado = Informe.objects.select_for_update().get(pk=informe.pk)  # CORREGIDO
                            
                            # Verificar que siga en estado editable
                            if informe_bloqueado.estado not in ESTADOS_EDITABLES:
                                messages.error(request, MSG_06_04)
                                _registrar_auditoria(
                                    usuario,
                                    informe_bloqueado,
                                    'Enviar informe',
                                    RESULTADO_BLOQUEADO,
                                    f'Intento de envío en estado: {informe_bloqueado.estado}',
                                )
                            else:
                                informe_bloqueado = form.save(commit=False)
                                informe_bloqueado.estado = EstadoTramite.EN_REVISION
                                informe_bloqueado.fecha_envio = timezone.now()

                                es_reenvio = (estado_anterior == EstadoTramite.REQUIERE_MODIFICACION)
                                if es_reenvio:
                                    informe_bloqueado.version_entrega += 1

                                informe_bloqueado.save()

                                # Historial
                                HistorialEstado.objects.create(
                                    informe=informe_bloqueado,
                                    usuario=usuario,
                                    estado_anterior=estado_anterior,
                                    estado_nuevo=EstadoTramite.EN_REVISION,
                                    tipo_accion='envio_informe',
                                    fecha_hora=timezone.now(),
                                )

                                # Auditoría
                                accion_auditoria = 'Reenviar informe' if es_reenvio else 'Enviar informe'
                                _registrar_auditoria(
                                    usuario,
                                    informe_bloqueado,
                                    accion_auditoria,
                                    RESULTADO_EXITO,
                                    f'Código: {informe_bloqueado.codigo} | Versión: {informe_bloqueado.version_entrega}',
                                )

                                # Notificación al Director
                                from apps.personas.models import DirectorCarrera
                                director_carrera = DirectorCarrera.objects.filter(
                                    carrera=propuesta.proceso.estudiante_carrera.carrera,
                                    activo=True,
                                ).first()

                                if director_carrera:
                                    Notificacion.objects.create(
                                        usuario=director_carrera.director.usuario,
                                        informe=informe_bloqueado,
                                        tipo='informe_enviado_revision',
                                        mensaje=(
                                            f'El estudiante {usuario.nombre} ha enviado '
                                            f'su informe ({informe_bloqueado.codigo}) para revisión.'
                                        ),
                                        fecha_creacion=timezone.now(),
                                    )

                                messages.success(request, MSG_06_02)
                                return redirect('informes:montaje')
                    except IntegrityError:
                        messages.error(request, 'El informe ya fue enviado. No se puede enviar dos veces.')
                        return redirect('informes:montaje')
    else:
        # GET: Solo obtener el informe, NO crearlo
        informe = Informe.objects.filter(
            propuesta=propuesta,
            archivado=False,
        ).exclude(estado=EstadoTramite.RECHAZADO).first()
        
        form = InformeForm(instance=informe) if informe else None

    # Si no hay informe (GET sin informe), mostrar botón "Crear Informe"
    if not informe:
        return render(request, 'informes/montaje/inicio.html', {
            'propuesta': propuesta,
            'informe': None,
            'form': None,
            'sin_acceso': False,
            'mostrar_boton_crear': True,
            'minimo_caracteres': MINIMO_CARACTERES,
        })

    bloqueado = informe.estado in ESTADOS_BLOQUEADOS

    # --- Observación del Director (SISTRA-07) ---
    ultima_observacion = None
    if informe.estado == EstadoTramite.REQUIERE_MODIFICACION:
        ultima_observacion = HistorialEstado.objects.filter(
            informe=informe,
            estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
        ).order_by('-fecha_hora').first()

    # --- Avance actualizado ---
    informe.refresh_from_db()
    avance = _calcular_avance(informe)

    # --- Clases Bootstrap ---
    if avance == 100:
        clase_progreso = 'bg-success'
    elif avance >= 50:
        clase_progreso = 'bg-warning text-dark'
    else:
        clase_progreso = 'bg-danger'

    clases_estado = {
        'Borrador': 'bg-secondary',
        'En revisión': 'bg-warning text-dark',
        'Requiere modificación': 'bg-info text-dark',
        'Aprobado': 'bg-success',
        'Rechazado': 'bg-danger',
        'Subido en UP': 'bg-primary',
        'Aprobado en UP': 'bg-primary',
    }
    clase_estado = clases_estado.get(informe.estado, 'bg-secondary')

    context = {
        'propuesta': propuesta,
        'informe': informe,
        'form': form,
        'avance': avance,
        'bloqueado': bloqueado,
        'ultima_observacion': ultima_observacion,
        'clase_progreso': clase_progreso,
        'clase_estado': clase_estado,
        'sin_acceso': False,
        'minimo_caracteres': MINIMO_CARACTERES,
    }
    return render(request, 'informes/montaje/inicio.html', context)