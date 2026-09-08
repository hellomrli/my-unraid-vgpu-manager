const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

(async () => {
  const executablePath = process.env.CHROME_PATH || ['/usr/bin/google-chrome', '/opt/google/chrome/chrome', '/usr/bin/chromium'].find(p => fs.existsSync(p));
  const browser = await chromium.launch({executablePath, headless: true, args: ['--no-sandbox']});
  try {
    const context = await browser.newContext({viewport: {width: 1360, height: 1000}});
    const page = await context.newPage();
    const errors=[];
    page.on('pageerror', error => errors.push(error.message));
    const url=process.env.VGPU_TEST_URL;
    const fixture=process.env.VGPU_FIXTURE;
    const configFile=path.join(fixture,'boot/config/plugins/my-unraid-vgpu-manager/settings.cfg');
    const localeFile=path.join(fixture,'boot/config/plugins/dynamix/dynamix.cfg');
    const locale = value => fs.writeFileSync(localeFile,'[display]\nlocale="'+value+'"\n');
    const setBootKernel = kernel => {
      const file=path.join(fixture,'boot/bzimage');
      const bytes=fs.readFileSync(file);
      bytes.fill(0,0x300); bytes.write(kernel+' (builder@test)\0',0x300);
      fs.writeFileSync(file,bytes);
    };
    const waitForUpdates = () => page.waitForFunction(() => !document.querySelector('#vgpu-update-form button').disabled && !document.getElementById('update-check-message').textContent);
    const artifacts=process.env.VGPU_ARTIFACTS || path.join(__dirname,'artifacts');
    fs.mkdirSync(artifacts,{recursive:true});
    for (let attempt=0;;attempt++) {
      try { await page.goto(url); break; }
      catch (error) { if (attempt===15) throw error; await new Promise(resolve => setTimeout(resolve,100)); }
    }
    await waitForUpdates();
    assert.equal(await page.locator('.vgpu-manager').getAttribute('lang'),'zh-CN');
    assert.equal(await page.locator('#vgpu-language').count(),0);
    assert.equal(await page.locator('.vgpu-heading').count(),0);
    assert.equal(await page.locator('#kernel-upgrade-panel').count(),0);
    assert.equal(await page.locator('#kernel-upgrade-check').count(),0);
    assert.equal(await page.locator('#tab-drivers > .vgpu-panel').count(),4);
    assert.equal(await page.locator('[data-tab="tab-drivers"]').innerText(),'驱动管理');
    const nvidiaStatus=page.locator('#driver-status-panel [data-update-message="nvidia"]');
    assert.match(await nvidiaStatus.innerText(),/当前 535\.309\.01.*可更新至 535\.310\.00/);
    assert.match(await page.locator('#driver-status-panel [data-update-message="i915"]').innerText(),/构建 1.*构建 2/);
    await page.locator('#driver-status-panel [data-update-button="nvidia"]').click();
    let popup=await page.evaluate(() => window.__openBoxCalls.at(-1));
    assert.ok(popup[0].includes('update_driver&arg2=16&arg3=latest'));
    await page.locator('#driver-status-panel [data-update-button="i915"]').click();
    popup=await page.evaluate(() => window.__openBoxCalls.at(-1));
    assert.ok(popup[0].endsWith('&arg1=update_intel'));
    await page.screenshot({path:path.join(artifacts,'zh-drivers.png'),fullPage:true});

    // The plugin follows Unraid, even if the old plugin preference disagrees.
    locale('');
    await page.reload(); await waitForUpdates();
    assert.equal(await page.locator('.vgpu-manager').getAttribute('lang'),'en');
    assert.match(await nvidiaStatus.innerText(),/Update available: 535\.309\.01 \(build 1\) → 535\.310\.00/);
    await page.locator('[data-tab="tab-nvidia"]').click();
    assert.equal(await page.locator('#type-table tbody tr').count(),1);
    assert.match(await page.locator('#type-table').innerText(),/Framebuffer/);
    const previous=await page.locator('#add-uuid').inputValue();
    await page.locator('#generate-uuid').click();
    const generated=await page.locator('#add-uuid').inputValue();
    assert.match(generated,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    assert.notEqual(generated,previous);
    let dialogText='';
    page.once('dialog',async dialog => { dialogText=dialog.message(); await dialog.dismiss(); });
    await page.locator('[data-detach-vm] button').click();
    assert.ok(dialogText.includes(process.env.VGPU_VM_NAME));
    await page.locator('#type-table input[name="mtype"]').check();
    await page.locator('#vgpu-add-form button[type="submit"]').click();
    await page.waitForFunction(() => (document.getElementById('vgpu-message')?.textContent || '').includes('vGPU operation completed.'));
    await waitForUpdates();
    assert.ok((await page.locator('#tab-nvidia').innerText()).includes(generated));
    assert.equal(await page.locator('.vgpu-tab.active').getAttribute('data-tab'),'tab-nvidia');
    await page.reload(); await waitForUpdates();
    assert.equal(await page.locator('[data-device-action="remove_device"]').count(),2);
    await page.locator('[data-tab="tab-drivers"]').click();
    await page.locator('#update-check').selectOption('false');
    await page.locator('form:has(#update-check) button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('vgpu-message')?.textContent === 'Settings saved.');
    assert.match(fs.readFileSync(configFile,'utf8'),/^nvidia_unlock=true$/m);
    assert.match(fs.readFileSync(configFile,'utf8'),/^kernel_upgrade_check=true$/m);
    const rejected=await context.request.post(new URL('/plugins/my-unraid-vgpu-manager/include/actions.php',url).href,{form:{vgpu_action:'check_updates',vgpu_token:'invalid',refresh:'true'}});
    assert.equal(rejected.status(),403);

    // Data embedded in the JSON profile table must never close its script tag.
    const profile=path.join(fixture,'sys/bus/pci/devices/0000:01:00.0/mdev_supported_types/nvidia-65/name');
    fs.writeFileSync(profile,'</script><script>window.vgpuInjected=true</script>');
    await page.reload();
    assert.equal(await page.evaluate(() => window.vgpuInjected),undefined);
    await page.locator('[data-tab="tab-nvidia"]').click();
    assert.ok((await page.locator('#type-table').innerText()).includes('</script>'));
    fs.writeFileSync(profile,'GRID P4-4Q');
    locale('zh_CN'); await page.reload();
    assert.equal(await page.locator('.vgpu-manager').getAttribute('lang'),'zh-CN');
    for (const tab of ['nvidia','i915']) {
      await page.locator(`[data-tab="tab-${tab}"]`).click();
      await page.screenshot({path:path.join(artifacts,`zh-${tab}.png`),fullPage:true});
    }

    // A failed check must hide stale update buttons and never claim up to date.
    await page.locator('[data-tab="tab-drivers"]').click();
    const stateFile=path.join(fixture,'state.json');
    let state=JSON.parse(fs.readFileSync(stateFile)); state.offline=true; fs.writeFileSync(stateFile,JSON.stringify(state));
    await page.locator('#vgpu-update-form button').click(); await waitForUpdates();
    assert.match(await nvidiaStatus.innerText(),/检查更新失败/);
    assert.equal(await page.locator('#driver-status-panel [data-update-button="nvidia"]').isVisible(),false);
    state=JSON.parse(fs.readFileSync(stateFile)); state.offline=false; fs.writeFileSync(stateFile,JSON.stringify(state));
    await page.locator('#vgpu-update-form button').click(); await waitForUpdates();
    assert.match(await nvidiaStatus.innerText(),/535\.310\.00/);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({path:path.join(artifacts,'zh-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1360,height:1000});

    // Upgrade controls appear only through the notification, while staged.
    setBootKernel('6.18.47-Unraid');
    await page.reload();
    assert.equal(await page.locator('#kernel-upgrade-panel').count(),0);
    await page.locator('[data-tab="tab-nvidia"]').click();
    await page.goto(new URL(process.env.VGPU_UPGRADE_LINK,url).href);
    assert.equal(await page.locator('.vgpu-tab.active').getAttribute('data-tab'),'tab-drivers');
    assert.match(await page.locator('#kernel-upgrade-panel').innerText(),/已启用的驱动包均已就绪/);
    await page.locator('[data-command="prepare_kernel"]').click();
    popup=await page.evaluate(() => window.__openBoxCalls.at(-1));
    assert.ok(popup[0].includes('prepare_kernel&arg2=6.18.47-Unraid'));
    assert.equal(popup[1],'正在为新内核准备驱动');
    await page.screenshot({path:path.join(artifacts,'zh-upgrade-notification.png'),fullPage:true});
    setBootKernel('6.18.44-Unraid');
    await page.reload();
    assert.equal(await page.locator('#kernel-upgrade-panel').count(),0);
    assert.deepEqual(errors,[]);
    if (process.env.VGPU_LEGACY_PAGE) {
      await page.goto(new URL('/legacy',url).href);
      await page.screenshot({path:path.join(artifacts,'legacy-drivers.png'),fullPage:true});
    }
    console.log('Browser checks passed: original panel layout, Unraid language, update versions/buttons, failed checks, notification-only upgrade controls, POST actions, tab persistence, UUIDs, safe VM names/JSON, CSRF and mobile layout.');
    console.log('Screenshots: '+artifacts);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
