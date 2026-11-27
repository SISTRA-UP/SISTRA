// static/js/inactividad.js
(function () {
  const TIEMPO_LIMITE_MS = 15 * 60 * 1000; // 15 minutos
  let temporizador;

  function cerrarSesionPorInactividad() {
    const formLogout = document.getElementById('sistraLogoutForm');
    if (formLogout) {
      formLogout.submit();
    }
  }

  function reiniciarTemporizador() {
    clearTimeout(temporizador);
    temporizador = setTimeout(cerrarSesionPorInactividad, TIEMPO_LIMITE_MS);
  }

  ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart'].forEach(function (evento) {
    document.addEventListener(evento, reiniciarTemporizador, { passive: true });
  });

  reiniciarTemporizador();
})();
