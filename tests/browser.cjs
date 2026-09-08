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
    for (let attempt=0;;attempt++) {
      try { await page.goto(url); break; }
      catch (error) { if (attempt===15) throw error; await new Promise(resolve => setTimeout(resolve,100)); }
    }
    assert.equal(await page.locator('.vgpu-manager').getAttribute('lang'),'zh-CN');
    assert.equal(await page.locator('[data-tab="tab-drivers"]').innerText(),'驱动管理');
    assert.match(await page.locator('#kernel-upgrade-panel').innerText(),/已启用的驱动包均已就绪/);
    await page.locator('#vgpu-language').selectOption('en');
    await page.locator('.vgpu-language button').click();
    await page.waitForFunction(() => document.querySelector('.vgpu-manager')?.lang === 'en' && document.getElementById('vgpu-message')?.textContent === 'Language saved.');
    assert.match(await page.locator('#vgpu-message').innerText(),/Language saved/);
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
    assert.ok((await page.locator('#tab-nvidia').innerText()).includes(generated));
    assert.equal(await page.locator('.vgpu-tab.active').getAttribute('data-tab'),'tab-nvidia');
    await page.reload();
    assert.equal(await page.locator('[data-device-action="remove_device"]').count(),2);
    await page.locator('[data-tab="tab-drivers"]').click();
    await page.locator('#update-check').selectOption('false');
    await page.locator('form:has(#update-check) button[type="submit"]').click();
    await page.waitForFunction(() => document.getElementById('vgpu-message')?.textContent === 'Settings saved.');
    const configFile=path.join(process.env.VGPU_FIXTURE,'boot/config/plugins/my-unraid-vgpu-manager/settings.cfg');
    assert.match(fs.readFileSync(configFile,'utf8'),/^nvidia_unlock=true$/m);
    await page.locator('[data-command="prepare_kernel"]').click();
    const popup=await page.evaluate(() => window.__openBoxCalls.at(-1));
    assert.ok(popup[0].includes('prepare_kernel&arg2=6.18.47-Unraid'));
    assert.equal(popup[1],'Preparing drivers for the next kernel');
    const rejected=await context.request.post(new URL('/plugins/my-unraid-vgpu-manager/include/actions.php',url).href,{form:{vgpu_action:'save_language',vgpu_token:'invalid',ui_language:'zh_CN'}});
    assert.equal(rejected.status(),403);
    assert.match(fs.readFileSync(configFile,'utf8'),/^ui_language=en$/m);
    // Data embedded in the JSON profile table must never close its script tag.
    const profile=path.join(process.env.VGPU_FIXTURE,'sys/bus/pci/devices/0000:01:00.0/mdev_supported_types/nvidia-65/name');
    fs.writeFileSync(profile,'</script><script>window.vgpuInjected=true</script>');
    await page.reload();
    assert.equal(await page.evaluate(() => window.vgpuInjected),undefined);
    await page.locator('[data-tab="tab-nvidia"]').click();
    assert.ok((await page.locator('#type-table').innerText()).includes('</script>'));
    fs.writeFileSync(profile,'GRID P4-4Q');
    await page.locator('#vgpu-language').selectOption('zh_CN');
    await page.locator('.vgpu-language button').click();
    await page.waitForFunction(() => document.querySelector('.vgpu-manager')?.lang === 'zh-CN');
    const artifacts=process.env.VGPU_ARTIFACTS || path.join(__dirname,'artifacts');
    fs.mkdirSync(artifacts,{recursive:true});
    for (const tab of ['drivers','nvidia','i915']) {
      await page.locator(`[data-tab="tab-${tab}"]`).click();
      await page.screenshot({path:path.join(artifacts,`zh-${tab}.png`),fullPage:true});
    }
    await page.setViewportSize({width:390,height:844});
    await page.locator('[data-tab="tab-drivers"]').click();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({path:path.join(artifacts,'zh-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('Browser checks passed: Chinese/English, POST actions, tab persistence, UUIDs, safe VM names/JSON, upgrade popup, CSRF and mobile layout.');
    console.log('Screenshots: '+artifacts);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
