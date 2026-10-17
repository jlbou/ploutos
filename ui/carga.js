// La pantalla de carga, sin depender de panel.js: si a los 15 s no ha llegado ninguna foto, dice donde mirar.
// Va en su fichero y no en la pagina: la CSP (api/guardia.py) no deja ejecutar scripts en linea.
"use strict";
setTimeout(function () {
  var c = document.getElementById("carga");
  if (!c || c.classList.contains("fuera")) return;
  document.getElementById("carga-txt").hidden = true;
  document.getElementById("carga-txt-2").hidden = false;
}, 15000);
