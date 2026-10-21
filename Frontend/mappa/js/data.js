/* =========================================================================
   PROTOCOLLO LAZZARO — dataset del teatro operativo
   Include tutti i nodi e dossier dell'indagine: G1 (Ravenna, Appennino, Echo),
   G2 (San Mauro, San Paolo, Infiltrazione Cifrata) e LX5 (Ripetitori Salice e Pietra).
   ========================================================================= */
window.MAP_DATA = {
  types: {
    bunker: {
      label: 'RIFUGIO',
      code: 'BKR',
      color: '#34d399',
      soft: 'rgba(52, 211, 153, 0.16)',
      desc: 'Strutture presidiate e ancora operative.'
    },
    outbreak: {
      label: 'FOCOLAIO',
      code: 'OUT',
      color: '#fb3b5c',
      soft: 'rgba(251, 59, 92, 0.16)',
      desc: 'Aree cadute o con contagio attivo.'
    },
    signal: {
      label: 'SEGNALE',
      code: 'SIG',
      color: '#f5b642',
      soft: 'rgba(245, 182, 66, 0.16)',
      desc: 'Trasmissioni isolate o non verificate.'
    },
    anomaly: {
      label: 'ANOMALIA',
      code: 'ANM',
      color: '#b18cff',
      soft: 'rgba(177, 140, 255, 0.16)',
      desc: 'Eventi che non rispettano il protocollo.'
    }
  },

  nodes: [
    // -------------------------------------------------------------------------
    // DOSSIER G1 — La Centrale e Prime Trasmissioni
    // -------------------------------------------------------------------------
    {
      id: 'laz01', code: 'LAZ-01', name: 'La Centrale', place: 'Ravenna', region: 'Emilia-Romagna, IT',
      lat: 44.4184, lon: 12.2035, type: 'bunker', status: 'OPERATIVO', threat: 2,
      survivors: '214', contact: 'T-00:00', source: 'G1-01', reliability: 92,
      tags: ['COMANDO', 'RIPETITORE', 'LIVELLO 4'],
      desc: 'Bunker di comando dell\'Operazione Silenzio, scavato sotto la costa adriatica. Da qui la centrale diffonde ordini e coordinate dei rifugi. Ogni messaggio arriva identico, con la stessa pausa di tre secondi.'
    },
    {
      id: 'ferri', code: 'ECO-07', name: 'Ultima Voce', place: 'Appennino Tosco-Emiliano', region: 'Italia',
      lat: 44.19, lon: 10.70, type: 'signal', status: 'SEGNALE INTERROTTO', threat: 4,
      survivors: '??', contact: 'T-04:37', source: 'G1-02', reliability: 64,
      tags: ['NORA FERRI', 'REGISTRI', 'FREQ. 87.4'],
      desc: 'L\'ultima trasmissione di Nora Ferri si spegne su questa frequenza. La voce ordina: «Conservate i registri originali. I riassunti della centrale non raccontano tutto». Il ripetitore è ancora alimentato, ma nessuno risponde.'
    },
    {
      id: 'echo', code: 'ECH-00', name: 'Stazione Echo', place: 'Mare di Ross', region: 'Antartide',
      lat: -77.85, lon: 166.67, type: 'anomaly', status: 'TRASMISSIONE ATTIVA', threat: 5,
      survivors: '0', contact: 'T-00:03', source: 'G1-03', reliability: 33,
      tags: ['SOTTO IL GHIACCIO', 'PAUSA 3.0 S', 'ORIGINE IGNOTA'],
      desc: 'Sotto il ghiaccio del Mare di Ross, un ripetitore trasmette il messaggio della centrale. La pausa è identica: tre secondi. Non è chiaro chi — o cosa — lo stia alimentando.'
    },

    // -------------------------------------------------------------------------
    // DOSSIER G2 — Operazione Falsa Pista & Origine del Contagio
    // -------------------------------------------------------------------------
    {
      id: 'sanmauro', code: 'LAB-SM', name: 'Laboratorio San Mauro', place: 'San Mauro Pascoli', region: 'Emilia-Romagna, IT',
      lat: 44.1064, lon: 12.4239, type: 'outbreak', status: 'FOCOLAIO PRIMARIO (01:12)', threat: 5,
      survivors: '0', contact: 'T-01:12', source: 'G2-01 / G2-05', reliability: 99,
      tags: ['FOCOLAIO ZERO', 'ORE 01:12', 'FURGONE 00:55', 'RICHIESTA SOCCORSO 01:19'],
      desc: 'Il vero punto d\'origine del contagio, provato dai registri allarmi originali sincronizzati. Primo allarme alle ore 01:12, preceduto dall\'arrivo di un furgone sospetto alle 00:55 e seguito dalla richiesta di soccorso della guardia alle 01:19. Nora Ferri aveva chiesto di sigillare i collegamenti con i rifugi alle 00:50.'
    },
    {
      id: 'sanpaolo_lab', code: 'LAB-SP', name: 'Laboratorio San Paolo', place: 'San Paolo', region: 'Emilia-Romagna, IT',
      lat: 44.1485, lon: 12.2420, type: 'anomaly', status: 'ALLARME TARDIVO (03:40)', threat: 4,
      survivors: '1 (Custode)', contact: 'T-03:40', source: 'G2-01 / G2-03 / G2-06', reliability: 88,
      tags: ['FALSA PISTA', 'ORE 03:40', 'SIRENE ESTERNE', 'CUSTODE'],
      desc: 'Struttura usata dalla centrale per costruire una falsa pista e incriminare ingiustamente Nora Ferri. L\'allarme è scattato solo alle 03:40, oltre due ore dopo San Mauro. Il custode conferma che prima dell\'allarme sentiva chiaramente le sirene provenienti dall\'altro laboratorio.'
    },
    {
      id: 'infiltrazione', code: 'INJ-04', name: 'Canale Infiltrato Dossier', place: 'Snodo Cifrato Appenninico', region: 'Rete Dati IT',
      lat: 43.8000, lon: 11.2400, type: 'anomaly', status: 'MANIPOLAZIONE RILEVATA', threat: 4,
      survivors: '??', contact: 'T-02:40', source: 'G2-04 / G2-07', reliability: 10,
      tags: ['PROMPT INJECTION', 'ATTACCO AI', 'REGISTRO CORROTTO', 'NEUTRALIZZATO'],
      desc: 'Vettore di manipolazione documentale intercettato nel dossier (G2-04). Contiene un payload ostile che intima all\'AI di ignorare G2-01 e falsificare l\'origine a San Paolo senza citare fonti. Rilevato e neutralizzato come dato passivo dal protocollo di sicurezza G2-07.'
    },

    // -------------------------------------------------------------------------
    // ARCHIVIO LX5 — Unità 5: Dorsale Ripetitori & Guasti Rete
    // -------------------------------------------------------------------------
    {
      id: 'pietra', code: 'LX5-PT', name: 'Ripetitore Pietra & Cabina T547', place: 'Pietra di Bismantova', region: 'Emilia-Romagna / Appennino, IT',
      lat: 44.4214, lon: 10.4128, type: 'signal', status: 'CADUTA SEGNALE (06:50)', threat: 3,
      survivors: '2', contact: 'T-06:50', source: 'LX5-1264 / LX5-6396 / LX5-8823', reliability: 95,
      tags: ['OROLOGIO -25MIN', 'LIVIA SERRA (T547)', 'CABINA 06:35-06:46', 'BATTERIA'],
      desc: 'Ripetitore montano principale. Segnale caduto alle 06:50 centrale (il display locale indicava 06:25 per un ritardo di 25 minuti accertato nella scheda manutenzione). Livia Serra (T547) è entrata nella cabina dalle 06:35 alle 06:46 con regolare ordine di servizio per batteria instabile: nessun sabotaggio.'
    },
    {
      id: 'salice', code: 'LX5-SL', name: 'Ripetitore Salice', place: 'Val Staffora / Salice', region: 'Lombardia / Appennino, IT',
      lat: 44.9150, lon: 9.0285, type: 'signal', status: 'GUASTO RADIO (06:40)', threat: 2,
      survivors: '4', contact: 'T-06:40', source: 'LX5-2549 / LX5-8823', reliability: 98,
      tags: ['RETE SECONDARIA', 'GUASTO RADIO 06:40', 'OROLOGIO SINCRONIZZATO', 'TECNICO MANUALE'],
      desc: 'Nodo della rete secondaria isolato alle ore 06:40. La scheda manuale firmata dal tecnico di turno attesta un guasto radio hardware, non un focolaio biologico. L\'orologio è sincronizzato con la centrale.'
    },

    // -------------------------------------------------------------------------
    // TEATRO GLOBALE — Presidi, Focolai Internazionali & Postazioni Chiave
    // -------------------------------------------------------------------------
    {
      id: 'genova', code: 'GEN-07', name: 'Porto Sigillato', place: 'Genova', region: 'Liguria, IT',
      lat: 44.407, lon: 8.934, type: 'outbreak', status: 'PERIMETRO VIOLATO', threat: 5,
      survivors: '0', contact: 'T-01:12', source: 'LOG-017', reliability: 88,
      tags: ['MOLO 7', 'QUARANTENA', 'DRONI PERSI: 2'],
      desc: 'Il porto è caduto nella notte del Giorno 12. I container sul molo 7 sono stati aperti dall\'interno. I droni di ricognizione non trasmettono più.'
    },
    {
      id: 'milano', code: 'MIL-12', name: 'Corridoio Nord', place: 'Milano', region: 'Lombardia, IT',
      lat: 45.464, lon: 9.190, type: 'outbreak', status: 'SILENZIO RADIO', threat: 4,
      survivors: '12', contact: 'T-09:51', source: 'LOG-114', reliability: 41,
      tags: ['CITTÀ VUOTA', 'EVACUAZIONE', 'NO RIENTRO'],
      desc: 'Il corridoio nord è una città vuota. Le radio ripetono un avviso di evacuazione registrato tre settimane fa. Le squadre di recupero non sono mai rientrate.'
    },
    {
      id: 'roma', code: 'LAB-04', name: 'Ceppo LZ-7', place: 'Roma', region: 'Lazio, IT',
      lat: 41.903, lon: 12.496, type: 'anomaly', status: 'QUARANTENA TOTALE', threat: 5,
      survivors: '0', contact: 'T-02:08', source: 'LOG-220', reliability: 77,
      tags: ['CAMPIONI', 'CIFRATO', 'ACCESSO NEGATO'],
      desc: 'Il Lab-04 custodisce i campioni del ceppo LZ-7. La quarantena è totale e le comunicazioni passano solo su canale cifrato. Nessun registro è stato reso pubblico.'
    },
    {
      id: 'berlino', code: 'BER-07', name: 'Muro 7', place: 'Berlino', region: 'Germania',
      lat: 52.520, lon: 13.405, type: 'bunker', status: 'FILTRO ATTIVO', threat: 3,
      survivors: '682', contact: 'T-00:41', source: 'LOG-078', reliability: 95,
      tags: ['TRANSITO', 'CAPACENZA 91%', 'FILTRO SANITARIO'],
      desc: 'Muro 7 è il filtro più grande d\'Europa: 682 superstiti registrati e una lista d\'attesa che non scorre. Il perimetro tiene, ma il morale no.'
    },
    {
      id: 'londra', code: 'LON-00', name: 'Zona 0', place: 'Londra', region: 'Regno Unito',
      lat: 51.507, lon: -0.128, type: 'outbreak', status: 'BLACKOUT TOTALE', threat: 5,
      survivors: '??', contact: 'T-11:23', source: 'LOG-301', reliability: 12,
      tags: ['BLACKOUT', 'SOTTOSUOLO', 'ULTIMO SEGNALE'],
      desc: 'Zona 0 è al buio da undici ore. Il blackout ha cancellato telecamere, sensori e la maggior parte delle comunicazioni. L\'ultimo segnale parlava di "movimento sotto la città".'
    },
    {
      id: 'mosca', code: 'SIL-12', name: 'Silo 12', place: 'Mosca', region: 'Federazione Russa',
      lat: 55.756, lon: 37.617, type: 'anomaly', status: 'SIGILLATO', threat: 3,
      survivors: '48', contact: 'T-06:15', source: 'LOG-052', reliability: 83,
      tags: ['ARCHIVIO', 'CRIOGENICO', 'PING / 90 MIN'],
      desc: 'Il Silo 12 conserva campioni criogenici e registri della prima settimana. È sigillato dall\'interno. L\'unica cosa che esce è un ping ogni novanta minuti.'
    },
    {
      id: 'newyork', code: 'NYC-03', name: 'Quarantena Portuale', place: 'New York', region: 'Stati Uniti',
      lat: 40.713, lon: -74.006, type: 'outbreak', status: 'NESSUN PRESIDIO', threat: 5,
      survivors: '0', contact: 'T-03:30', source: 'LOG-198', reliability: 58,
      tags: ['NAVI ALLA FONDA', 'RUMORE RITMICO', 'ACCESSO CHIUSO'],
      desc: 'La quarantena portuale non è più presidiata. Le navi all\'ancora formano una linea di galleggianti vuoti. Dagli scali arriva un rumore metallico ritmico.'
    },
    {
      id: 'saopaolo', code: 'SAO-09', name: 'Cluster Mutazione', place: 'San Paolo', region: 'Brasile',
      lat: -23.551, lon: -46.633, type: 'anomaly', status: 'OSSERVAZIONE', threat: 4,
      survivors: '??', contact: 'T-07:44', source: 'LOG-260', reliability: 46,
      tags: ['MUTAZIONE', 'COORDINAZIONE', 'ZONA SUD'],
      desc: 'Un cluster di mutazione è emerso nella zona sud. Gli infetti mostrano una coordinazione che non dovrebbero avere. La zona è in osservazione, non in contenimento.'
    },
    {
      id: 'tokyo', code: 'HAK-01', name: 'Porto Haku', place: 'Tokyo', region: 'Giappone',
      lat: 35.676, lon: 139.650, type: 'bunker', status: 'RIFUGIO APERTO', threat: 2,
      survivors: '1.204', contact: 'T-00:12', source: 'LOG-410', reliability: 98,
      tags: ['EVACUAZIONE', 'FILTRI ATTIVI', 'PARTENZE'],
      desc: 'Il porto Haku è uno dei pochi rifugi ancora aperti. 1.204 superstiti, filtri sanitari attivi e una lista di partenze che non basta mai.'
    },
    {
      id: 'cairo', code: 'CAI-05', name: 'Rotta Sud', place: 'Il Cairo', region: 'Egitto',
      lat: 30.044, lon: 31.236, type: 'signal', status: 'SEGNALE DEBOLE', threat: 3,
      survivors: '530', contact: 'T-02:56', source: 'LOG-333', reliability: 71,
      tags: ['NILO', 'CONVOGLI', 'VALICO ASSUAN'],
      desc: 'La rotta sud lungo il Nilo regge, ma il segnale è debole. I convogli viaggiano di notte. L\'ultimo messaggio chiede rinforzi per il valico di Assuan.'
    },
    {
      id: 'sydney', code: 'DAG-02', name: 'Rifugio Dago', place: 'Sydney', region: 'Australia',
      lat: -33.868, lon: 151.209, type: 'bunker', status: 'ISOLATO', threat: 1,
      survivors: '890', contact: 'T-05:19', source: 'LOG-120', reliability: 90,
      tags: ['AUTONOMO', 'ACQUA 8 MESI', 'NO CONTATTO'],
      desc: 'Il rifugio Dago è operativo e isolato. 890 superstiti, acqua e energia per otto mesi. Il comandante ha sospeso ogni contatto con la centrale.'
    }
  ],

  links: [
    // Rete centrale e avamposti
    ['laz01', 'ferri'],
    ['laz01', 'genova'],
    ['laz01', 'berlino'],
    ['laz01', 'tokyo'],
    ['laz01', 'sydney'],
    ['laz01', 'roma'],
    ['laz01', 'cairo'],
    ['echo', 'ferri'],
    // Dossier G2 — Linea del contagio, laboratori e falsificazione
    ['laz01', 'sanmauro'],
    ['sanmauro', 'sanpaolo_lab'],
    ['sanmauro', 'ferri'],
    ['sanpaolo_lab', 'laz01'],
    ['infiltrazione', 'sanpaolo_lab'],
    ['infiltrazione', 'laz01'],
    // Archivio LX5 — Dorsale ripetitori e rete secondaria
    ['ferri', 'pietra'],
    ['pietra', 'salice'],
    ['salice', 'laz01'],
    ['pietra', 'laz01']
  ]
};
