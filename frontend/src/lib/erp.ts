import { useEffect, useState } from 'react';
import { getDefontanaStatus } from '../api/integrations';

/**
 * Qué se ESCRIBE hoy al ERP, según la configuración del servidor.
 *
 * Las pantallas que confirman una operación lo necesitan para advertir ANTES: con
 * ``erp_sync_enabled`` encendido, confirmar un despacho emite una guía real en Defontana
 * que consume folio y no se puede borrar. Mientras no se sepa, se asume el caso peligroso
 * (que sí viaja), porque el aviso de más no rompe nada y el de menos sí.
 */
export interface BanderasErp {
  despachoViajaAlErp: boolean;
  inventarioViajaAlErp: boolean;
  cargando: boolean;
}

export function useBanderasErp(): BanderasErp {
  const [flags, setFlags] = useState<BanderasErp>({
    despachoViajaAlErp: true,
    inventarioViajaAlErp: true,
    cargando: true,
  });

  useEffect(() => {
    let vigente = true;
    getDefontanaStatus()
      .then((s) => {
        if (!vigente) return;
        setFlags({
          despachoViajaAlErp: s.erp_sync_enabled ?? true,
          inventarioViajaAlErp: s.erp_inventory_sync_enabled ?? true,
          cargando: false,
        });
      })
      .catch(() => {
        if (vigente) setFlags((f) => ({ ...f, cargando: false }));
      });
    return () => {
      vigente = false;
    };
  }, []);

  return flags;
}
