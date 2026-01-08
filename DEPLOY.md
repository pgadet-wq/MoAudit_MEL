# Déploiement MoA_MEL Audit sur Scaleway

## Prérequis

- Serveur Scaleway (Ubuntu 20.04+ ou Debian 11+)
- Accès SSH root
- Port 8080 ouvert dans le firewall
- Clé API Mistral (optionnelle mais recommandée)

## Installation rapide (5 minutes)

### 1. Connectez-vous à votre serveur Scaleway

```bash
ssh root@VOTRE_IP_SCALEWAY
```

### 2. Téléchargez et exécutez le script d'installation

```bash
curl -sSL https://raw.githubusercontent.com/pgadet-wq/MoAudit_MEL/main/deploy.sh | bash
```

Ou manuellement :

```bash
git clone https://github.com/pgadet-wq/MoAudit_MEL.git /opt/moamel
cd /opt/moamel
chmod +x deploy.sh
./deploy.sh
```

### 3. Configurez votre clé API Mistral

```bash
nano /opt/moamel/.env
```

Remplacez `your_mistral_api_key_here` par votre vraie clé API.

### 4. Démarrez le service

```bash
systemctl start moamel
systemctl status moamel
```

### 5. Accédez à l'application

Ouvrez votre navigateur :
```
http://VOTRE_IP_SCALEWAY:8080/app
```

## Utilisation

### Workflow en 6 étapes

1. **Upload MMEL** - Chargez le fichier PDF MMEL
2. **Validation MMEL** - Vérifiez/corrigez le parsing (édition directe dans le tableau)
3. **Upload MEL** - Chargez le fichier PDF MEL
4. **Validation MEL** - Vérifiez/corrigez le parsing
5. **Audit** - Lancez la comparaison automatique
6. **Résultats** - Analysez les écarts et validez les items HITL

### Édition des items

- **Cliquez sur une cellule** pour la modifier
- **Annotations** : cliquez sur l'icône commentaire pour ajouter des notes
- Les modifications sont sauvegardées automatiquement

### Sessions et historique

- Toutes les sessions sont persistées en base de données
- Vous pouvez reprendre une session interrompue
- L'historique complet des audits est conservé

## Commandes utiles

```bash
# Voir les logs en temps réel
journalctl -u moamel -f

# Redémarrer le service
systemctl restart moamel

# Arrêter le service
systemctl stop moamel

# Vérifier le statut
systemctl status moamel
```

## Configuration avancée

### Changer le port

Éditez `/opt/moamel/.env` :
```
PORT=80
```

Puis redémarrez : `systemctl restart moamel`

### Activer HTTPS (avec Nginx)

```bash
apt install nginx certbot python3-certbot-nginx

# Configurer Nginx comme reverse proxy
cat > /etc/nginx/sites-available/moamel << 'EOF'
server {
    listen 80;
    server_name votre-domaine.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

ln -s /etc/nginx/sites-available/moamel /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Activer SSL
certbot --nginx -d votre-domaine.com
```

## Dépannage

### Le service ne démarre pas

```bash
# Vérifier les logs
journalctl -u moamel -n 50

# Tester manuellement
cd /opt/moamel/src
source ../venv/bin/activate
python server_v2.py
```

### Erreur de parsing PDF

Vérifiez que Docling est installé :
```bash
source /opt/moamel/venv/bin/activate
pip install docling
```

### Base de données corrompue

```bash
rm /opt/moamel/src/data/moamel_audit.db
systemctl restart moamel
```

## Support

Pour toute question, ouvrez une issue sur GitHub.
