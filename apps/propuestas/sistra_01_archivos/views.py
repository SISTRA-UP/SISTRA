"""
views.py — Vista única para crear/editar la propuesta del estudiante autenticado.

Acciones del POST (campo `accion`):
  guardar   -> "borrador"      Guarda y deja/mantiene estado BORRADOR (o REQUIERE_MODIFICACION si venía de ahí)
  autoguardar                  Igual que borrador pero responde JSON (llamado por JS)
  enviar                       Valida obligatorios, pasa a EN_REVISION, bloquea y notifica
  importar_word                Parsea el .docx y re-renderiza el formulario autocompletado (sin persistir)
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from .forms import PlantillaWordForm, PropuestaForm
from .models import CAMPOS_OBLIGATORIOS, ESTADOS_ACTIVOS, EstadoPropuesta, PropuestaTrabajoSocial
from .services import PlantillaInvalidaError, extraer_datos_plantilla, obtener_director


class PropuestaTrabajoSocialView(LoginRequiredMixin, View):
    template_name = "propuestas/template.html"

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _propuesta_activa(usuario, for_update=False):
        qs = PropuestaTrabajoSocial.objects.filter(estudiante=usuario, estado__in=ESTADOS_ACTIVOS)
        return (qs.select_for_update() if for_update else qs).first()

    @staticmethod
    def _es_ajax(request):
        return request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _render(self, request, form, propuesta, status=200):
        ctx = {
            "form": form,
            "propuesta": propuesta,
            "word_form": PlantillaWordForm(),
            "bloqueado": form.bloqueado,
            "progreso": propuesta.porcentaje_avance if propuesta else 0,
            "estado": propuesta.get_estado_display() if propuesta else EstadoPropuesta.BORRADOR.label,
        }
        return render(request, self.template_name, ctx, status=status)

    # ----------------------------------------------------------------- GET
    def get(self, request):
        propuesta = self._propuesta_activa(request.user)
        return self._render(request, PropuestaForm(instance=propuesta), propuesta)

    # ----------------------------------------------------------------- POST
    def post(self, request):
        accion = request.POST.get("accion", "guardar")
        if accion == "importar_word":
            return self._importar_word(request)

        try:
            with transaction.atomic():
                # Bloqueo de fila: evita doble envío / doble creación concurrente.
                propuesta = self._propuesta_activa(request.user, for_update=True)

                if propuesta and not propuesta.es_editable:
                    return self._error(request, "La propuesta está bloqueada para edición.", propuesta, 403)

                if propuesta is None:
                    propuesta = PropuestaTrabajoSocial(
                        estudiante=request.user, director=obtener_director(request.user)
                    )

                form = PropuestaForm(request.POST, instance=propuesta, accion=accion)
                if not form.is_valid():          # incluye PropuestaTrabajoSocial.clean() (única activa)
                    return self._form_invalido(request, form, propuesta)

                propuesta = form.save()          # conserva el estado actual (Borrador / Requiere modificación)
                if accion == "enviar":
                    propuesta.enviar()           # -> EN_REVISION + señal de notificación al Director
        except IntegrityError:
            # Carrera: el índice único parcial detectó una segunda propuesta activa.
            return self._error(request, "Ya tienes una propuesta activa.", None, 409)

        if self._es_ajax(request):
            return JsonResponse(
                {"ok": True, "estado": propuesta.estado, "progreso": propuesta.porcentaje_avance}
            )
        messages.success(
            request,
            "Propuesta enviada a revisión de tu Director." if accion == "enviar" else "Borrador guardado.",
        )
        return redirect("propuestas:propuesta_trabajo_social")

    # ----------------------------------------------------------------- Word
    def _importar_word(self, request):
        propuesta = self._propuesta_activa(request.user)
        if propuesta and not propuesta.es_editable:
            return self._error(request, "La propuesta está bloqueada para edición.", propuesta, 403)

        word_form = PlantillaWordForm(request.POST, request.FILES)
        form_actual = PropuestaForm(instance=propuesta)
        if not word_form.is_valid():
            for err in word_form.errors.get("archivo", []):
                messages.error(request, err)
            return self._render(request, form_actual, propuesta, status=400)

        try:
            datos = extraer_datos_plantilla(word_form.cleaned_data["archivo"])
        except PlantillaInvalidaError as exc:
            messages.error(request, str(exc))
            return self._render(request, form_actual, propuesta, status=400)

        if not datos:
            messages.warning(request, "No se encontraron campos reconocibles en la plantilla.")
            return self._render(request, form_actual, propuesta)

        # Valores actuales + valores importados (los importados prevalecen). Aún NO se guarda.
        inicial = model_to_dict(propuesta or PropuestaTrabajoSocial(), fields=CAMPOS_OBLIGATORIOS)
        inicial.update(datos)
        form = PropuestaForm(initial=inicial, instance=propuesta)
        messages.info(
            request,
            f"Se autocompletaron {len(datos)} campo(s). Revisa el contenido y pulsa «Guardar borrador».",
        )
        return self._render(request, form, propuesta)

    # ----------------------------------------------------------------- errores
    def _form_invalido(self, request, form, propuesta):
        if self._es_ajax(request):
            return JsonResponse({"ok": False, "errores": form.errors.get_json_data()}, status=400)
        return self._render(request, form, propuesta if propuesta.pk else None, status=400)

    def _error(self, request, mensaje, propuesta, status):
        if self._es_ajax(request):
            return JsonResponse({"ok": False, "errores": {"__all__": [{"message": mensaje}]}}, status=status)
        messages.error(request, mensaje)
        return redirect("propuestas:propuesta_trabajo_social")
