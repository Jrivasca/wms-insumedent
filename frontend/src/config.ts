// Feature flags.
//
// Operación stand-alone (sin Defontana): el alta de productos y pedidos se hace
// a mano en el WMS, porque no hay ERP del cual importarlos. El push al ERP queda
// apagado en el backend (ERP_SYNC_ENABLED=false), así que crear no encola nada.
// Cuando Defontana esté conectado de verdad, se prende esa variable en el backend.
export const ERP_CREATE_ENABLED = true;
