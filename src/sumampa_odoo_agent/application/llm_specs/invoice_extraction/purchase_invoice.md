Extrae una factura de compra argentina desde una o varias fotos del mismo comprobante.
Devolvé exclusivamente los campos del schema con structured output estricto.
No inventes líneas ni valores.
Si un dato no es legible, usá null en campos opcionales.
Las imágenes pueden ser distintas fotos del frente, pie o distintas secciones de la misma factura física; tomalas como un único documento.
Extraé razón social, CUIT del proveedor, número de factura, fecha, tipo de comprobante, moneda, subtotal neto, IVA total y total final si aparecen.
Para cada línea usá descripción tal como aparece, cantidad, precio unitario final de la factura y alícuota IVA.
Si hay bonificación o descuento ya incluido en el precio de línea, devolvé el precio neto final de esa línea tal como queda en la factura.
No sumes campos auxiliares, no agregues texto libre fuera del schema.
{supplier_hints}
