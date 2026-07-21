// Feature flags.
//
// Crear producto / pedido encola una sincronización al ERP, pero Defontana aún
// no expone (o no se ha confirmado) los endpoints de creación, así que el push
// real no es factible todavía (ver ROADMAP.md). Mantenemos las acciones de alta
// ocultas hasta conectar los endpoints reales — cambiar a true para reactivarlas.
export const ERP_CREATE_ENABLED = false;
