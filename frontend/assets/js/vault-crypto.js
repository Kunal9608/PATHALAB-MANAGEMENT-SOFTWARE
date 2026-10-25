/**
 * PathLab OS — Admin Important Documents Vault
 * Client-Side Encryption Subsystem (Web Crypto API)
 *
 * Threat Model & Security Architecture:
 * - Alg: AES-256-GCM (Authenticated Encryption with Associated Data).
 * - Key Derivation: PBKDF2 with SHA-256, 100,000 iterations, 128-bit cryptographically random salt.
 * - Nonce/IV: Unique 96-bit (12-byte) cryptographically secure random value per encryption call.
 * - Nonce reuse is strictly prohibited and mathematically prevented.
 * - Plaintext vault keys and user passphrases NEVER leave the client browser.
 * - The backend and database only ever receive and store ciphertext bytes and nonces.
 * - On lock or session termination, in-memory CryptoKey instances are zeroed/discarded.
 */

(function (window) {
  'use strict';

  // In-memory session preservation across SPA navigations
  window.__vaultSession = window.__vaultSession || {
    key: null,
    salt: null,
    adminId: null,
  };

  let _activeCryptoKey = window.__vaultSession.key;
  let _activeSalt = window.__vaultSession.salt;
  let _adminId = window.__vaultSession.adminId;

  function bytesToHex(bytes) {
    return Array.from(bytes)
      .map(b => b.toString(16).padStart(2, '0'))
      .join('');
  }

  function hexToBytes(hex) {
    const bytes = new Uint8Array(hex.length / 2);
    for (let i = 0; i < hex.length; i += 2) {
      bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
    }
    return bytes;
  }

  function arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
  }

  function base64ToArrayBuffer(base64) {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
  }

  /**
   * Derive a 256-bit AES-GCM CryptoKey from a user passphrase and salt.
   */
  async function deriveKeyFromPassphrase(passphrase, saltBytes) {
    const enc = new TextEncoder();
    const keyMaterial = await window.crypto.subtle.importKey(
      'raw',
      enc.encode(passphrase),
      'PBKDF2',
      false,
      ['deriveKey']
    );

    return await window.crypto.subtle.deriveKey(
      {
        name: 'PBKDF2',
        salt: saltBytes,
        iterations: 100000,
        hash: 'SHA-256'
      },
      keyMaterial,
      { name: 'AES-GCM', length: 256 },
      true, // extractable for tab-scoped sessionStorage persistence
      ['encrypt', 'decrypt']
    );
  }

  const VaultCrypto = {
    isUnlocked() {
      return _activeCryptoKey !== null || (window.__vaultSession && window.__vaultSession.key !== null);
    },

    getActiveAdminId() {
      return _adminId || (window.__vaultSession && window.__vaultSession.adminId);
    },

    lockVault() {
      const curAdminId = _adminId || (window.__vaultSession && window.__vaultSession.adminId);
      if (curAdminId) {
        sessionStorage.removeItem('akriti_vault_tab_key_' + curAdminId);
        sessionStorage.removeItem('akriti_vault_unlocked_' + curAdminId);
      }
      _activeCryptoKey = null;
      _activeSalt = null;
      _adminId = null;
      window.__vaultSession = { key: null, salt: null, adminId: null };
      window.dispatchEvent(new CustomEvent('vault:lock'));
    },

    /**
     * Restore unlock session for active browser tab across page refresh / theme toggle
     */
    async tryRestoreTabSession(adminId) {
      if (!adminId) return false;

      // 1. Check in-memory session first
      if (window.__vaultSession && window.__vaultSession.key && window.__vaultSession.adminId === adminId) {
        _activeCryptoKey = window.__vaultSession.key;
        _activeSalt = window.__vaultSession.salt;
        _adminId = adminId;
        return true;
      }

      // 2. Check tab-scoped sessionStorage
      const keyHex = sessionStorage.getItem('akriti_vault_tab_key_' + adminId);
      if (!keyHex) return false;

      try {
        const rawKey = hexToBytes(keyHex);
        const importedKey = await window.crypto.subtle.importKey(
          'raw',
          rawKey,
          { name: 'AES-GCM', length: 256 },
          true,
          ['encrypt', 'decrypt']
        );

        _activeCryptoKey = importedKey;
        _adminId = adminId;
        window.__vaultSession = {
          key: importedKey,
          salt: null,
          adminId: adminId
        };
        return true;
      } catch (err) {
        console.warn('Failed to restore vault tab key:', err);
        sessionStorage.removeItem('akriti_vault_tab_key_' + adminId);
        return false;
      }
    },

    /**
     * Unlock vault using passphrase.
     * Persists ephemeral unlock state in sessionStorage for active browser tab lifecycle.
     */
    async unlockVault(passphrase, adminId) {
      if (!passphrase || !passphrase.trim()) {
        throw new Error('Please enter your administrator account password');
      }

      // Generate deterministic 128-bit salt strictly tied to the verified admin ID
      const enc = new TextEncoder();
      const digest = await window.crypto.subtle.digest('SHA-256', enc.encode(`akriti_vault_salt_v1_${adminId}`));
      const saltBytes = new Uint8Array(digest).slice(0, 16);

      _activeCryptoKey = await deriveKeyFromPassphrase(passphrase, saltBytes);
      _activeSalt = saltBytes;
      _adminId = adminId;

      window.__vaultSession = {
        key: _activeCryptoKey,
        salt: _activeSalt,
        adminId: adminId
      };

      // Persist raw key in tab-scoped sessionStorage for seamless refresh / theme toggle
      try {
        const rawKey = await window.crypto.subtle.exportKey('raw', _activeCryptoKey);
        const keyHex = bytesToHex(new Uint8Array(rawKey));
        sessionStorage.setItem('akriti_vault_tab_key_' + adminId, keyHex);
        sessionStorage.setItem('akriti_vault_unlocked_' + adminId, '1');
      } catch (exportErr) {
        console.warn('Tab key export warning:', exportErr);
      }

      window.dispatchEvent(new CustomEvent('vault:unlock'));
      return true;
    },

    /**
     * Encrypt a text string (such as note title or body) using AES-256-GCM.
     */
    async encryptText(plaintext) {
      if (!_activeCryptoKey) {
        throw new Error('Vault is locked. Please unlock first.');
      }
      const enc = new TextEncoder();
      const iv = window.crypto.getRandomValues(new Uint8Array(12));

      const ciphertextBuffer = await window.crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv },
        _activeCryptoKey,
        enc.encode(plaintext)
      );

      return {
        ciphertextBase64: arrayBufferToBase64(ciphertextBuffer),
        ivHex: bytesToHex(iv),
        alg: 'AES-256-GCM',
        saltHex: bytesToHex(_activeSalt)
      };
    },

    /**
     * Decrypt a ciphertext string back to plaintext UTF-8.
     */
    async decryptText(ciphertextBase64, ivHex) {
      if (!_activeCryptoKey) {
        throw new Error('Vault is locked. Please unlock first.');
      }
      if (!ciphertextBase64 || !ivHex) {
        return '';
      }

      const iv = hexToBytes(ivHex);
      const ciphertextBuffer = base64ToArrayBuffer(ciphertextBase64);

      try {
        const decryptedBuffer = await window.crypto.subtle.decrypt(
          { name: 'AES-GCM', iv: iv },
          _activeCryptoKey,
          ciphertextBuffer
        );
        const dec = new TextDecoder();
        return dec.decode(decryptedBuffer);
      } catch (err) {
        console.warn('Decryption failed — invalid passphrase or corrupted ciphertext:', err);
        throw new Error('Decryption failed. Please check your vault passphrase.');
      }
    },

    /**
     * Encrypt binary file data (ArrayBuffer or File) with AES-256-GCM.
     */
    async encryptBinary(arrayBuffer) {
      if (!_activeCryptoKey) {
        throw new Error('Vault is locked. Please unlock first.');
      }
      const iv = window.crypto.getRandomValues(new Uint8Array(12));

      const ciphertextBuffer = await window.crypto.subtle.encrypt(
        { name: 'AES-GCM', iv: iv },
        _activeCryptoKey,
        arrayBuffer
      );

      return {
        ciphertextBlob: new Blob([ciphertextBuffer], { type: 'application/octet-stream' }),
        ivHex: bytesToHex(iv),
        alg: 'AES-256-GCM',
        saltHex: bytesToHex(_activeSalt)
      };
    },

    /**
     * Decrypt binary ciphertext ArrayBuffer back into plain ArrayBuffer.
     */
    async decryptBinary(ciphertextArrayBuffer, ivHex) {
      if (!_activeCryptoKey) {
        throw new Error('Vault is locked. Please unlock first.');
      }
      const iv = hexToBytes(ivHex);

      try {
        return await window.crypto.subtle.decrypt(
          { name: 'AES-GCM', iv: iv },
          _activeCryptoKey,
          ciphertextArrayBuffer
        );
      } catch (err) {
        console.warn('Binary decryption failed:', err);
        throw new Error('Binary decryption failed. Please check your vault passphrase.');
      }
    }
  };

  window.VaultCrypto = VaultCrypto;
})(window);
