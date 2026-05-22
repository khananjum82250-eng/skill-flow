// Dashboard Page Specific JS
document.addEventListener('DOMContentLoaded', () => {
    // Intercept Dashboard Skills Form
    const dashboardSkillsForm = document.getElementById('dashboardSkillsForm');
    
    if (dashboardSkillsForm) {
        dashboardSkillsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const skillsOffered = document.getElementById('dbSkillsOffered').value;
            const skillsWanted = document.getElementById('dbSkillsWanted').value;
            
            fetch('/update_skills', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    skills_offered: skillsOffered,
                    skills_wanted: skillsWanted
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Update the tags in the DOM
                    updateTags('tagsOffered', data.skills_offered, 'badge-purple');
                    updateTags('tagsWanted', data.skills_wanted, 'badge-secondary');
                    
                    SkillFlowUI.success('Skills updated successfully!');
                } else {
                    SkillFlowUI.error(data.error || 'Unable to update skills.');
                }
            })
            .catch(err => {
                console.error('Fetch error:', err);
                SkillFlowUI.error('Failed to save skills.');
            });
        });
    }
    
    function updateTags(containerId, skillsString, badgeClass) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        
        if (!skillsString) return;
        
        const skills = skillsString.split(',').map(s => s.trim()).filter(s => s);
        skills.forEach(skill => {
            const span = document.createElement('span');
            span.className = `badge ${badgeClass}`;
            span.textContent = skill;
            container.appendChild(span);
        });
    }
});

// Function to send request from dashboard
window.sendRequestDashboard = function(receiverId, skillRequested, skillOffered) {
    if (!receiverId) return;
    
    fetch('/api/request/send', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            receiver_id: receiverId,
            skill_requested: skillRequested.trim() || 'Skill',
            skill_offered: skillOffered.trim() || 'Skill'
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            SkillFlowUI.success('Request sent successfully!');
        } else {
            SkillFlowUI.error(data.error || 'Failed to send request.');
        }
    })
    .catch(err => {
        console.error('Fetch error:', err);
        SkillFlowUI.error('Failed to send request.');
    });
};
